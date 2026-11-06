'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const test = require('node:test');
const { AcceptanceLifecyclePage, ChildInvocation, redact } = require('./acceptance-lifecycle-page.js');
const { state } = require('../../features/support/app-lifecycle.js');
const repoRoot = path.resolve(__dirname, '../../..');

function fakeForkFactory(options = {}) {
  let sequence = 0;
  let active = 0;
  let maxActive = 0;
  const calls = [];
  const forkProcess = (file, args, spawnOptions) => {
    calls.push({ file, args, spawnOptions });
    active++;
    maxActive = Math.max(maxActive, active);
    const number = ++sequence;
    const child = new EventEmitter();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    child.connected = true;
    const secret = `private-run-credential-${number}`;
    const project = `sdd-acceptance-test-${number}`;
    let kind;
    let closed = false;
    function close(outcome, code) {
      if (closed) return;
      closed = true;
      const events = [{ type: 'stack-start', project, at: number * 100 }, { type: 'stack-ready', project, at: number * 100 + 1 },
        { type: 'stack-stopped', project, at: number * 100 + 2, ownedResourcesEmpty: true }];
      if (outcome === 'cancelled') events.push({ type: 'invocation-cancelled', signal: 'SIGTERM' });
      if (options.publicLeak) events.push({ type: 'accidental-secret', value: secret });
      child.emit('message', { type: 'result', result: { outcome, kind, project, diagnostics: {},
        events, cleanupVerified: true } });
      child.connected = false;
      child.stdout.end();
      child.stderr.end();
      active--;
      child.emit('close', code, null);
    }
    child.send = (message, callback) => {
      callback?.();
      queueMicrotask(() => {
        if (message.command === 'start') {
          kind = message.kind;
          child.emit('message', { type: 'private-credential', credential: secret });
          child.stdout.write(options.stdoutLeak ? secret.slice(0, 7) : 'safe redacted lifecycle log\n');
          if (options.stdoutLeak) child.stdout.write(secret.slice(7));
          child.emit('message', { type: 'ready', ready: { project, kind } });
        } else if (message.command === 'execute') close(kind === 'failure' ? 'failed' : 'completed', kind === 'failure' ? 1 : 0);
        else if (message.command === 'stop') close('aborted', 1);
      });
    };
    child.kill = signal => { queueMicrotask(() => close('cancelled', signal === 'SIGINT' ? 130 : 143)); return true; };
    return child;
  };
  return { forkProcess, calls, maxActive: () => maxActive };
}

function fakeDocker() {
  const resources = new Map();
  const calls = [];
  const removed = [];
  let number = 0;
  resources.set('pre-existing-unrelated-resource', { kind: 'volume', Labels: { 'com.docker.compose.project': 'pre-existing-project' } });
  const dockerOutput = async args => {
    calls.push(args);
    const filter = args.find(arg => arg.startsWith('label='));
    if (filter) {
      const scope = filter.slice('label='.length);
      const separator = scope.indexOf('=');
      const key = scope.slice(0, separator), value = scope.slice(separator + 1);
      const kind = args[0] === 'ps' ? 'container' : args[0];
      return [...resources].filter(([, info]) => info.kind === kind && info.Labels[key] === value).map(([id]) => id).join('\n');
    }
    const kind = args[0] === 'create' || args[0] === 'inspect' || args[0] === 'rm' ? 'container' : args[0];
    if (args.includes('create')) {
      const labels = {};
      args.forEach((argument, index) => {
        if (argument === '--label') {
          const label = args[index + 1], separator = label.indexOf('=');
          labels[label.slice(0, separator)] = label.slice(separator + 1);
        }
      });
      const id = `${kind}-fixture-${++number}`;
      resources.set(id, { kind, Id: id, Name: id, Labels: labels, Config: { Labels: labels }, State: { Running: false } });
      return id;
    }
    if (args.includes('inspect')) {
      const info = resources.get(args.at(-1));
      assert.ok(info, 'Unit test inspected a resource that does not exist');
      return JSON.stringify([info]);
    }
    if (args.includes('rm')) {
      const id = args.at(-1);
      assert.ok(resources.has(id), 'Unit test attempted duplicate deletion');
      removed.push(id);
      resources.delete(id);
      return id;
    }
    throw new Error(`Unhandled unit-test Docker operation ${JSON.stringify(args)}`);
  };
  return { dockerOutput, calls, removed, resources };
}

test('sentinel mount-order changes are harmless but changed mounted-volume identity still fails isolation', async () => {
  const docker = fakeDocker();
  const page = new AcceptanceLifecyclePage({}, { dockerOutput: docker.dockerOutput });
  await page.independentValidation();
  await page.addSentinelContainer();
  const container = docker.resources.get(page.sentinel.container);
  container.Mounts = [{ Destination: '/z', Name: 'z-volume' }, { Destination: '/a', Name: 'a-volume' }];
  page.sentinel.snapshot = await page.sentinelSnapshot();
  container.Mounts.reverse();
  await page.unrelatedUnchanged();
  container.Mounts[0].Name = 'changed-volume';
  await assert.rejects(page.unrelatedUnchanged(), /modified unrelated/);
  container.Mounts[0].Name = 'a-volume';
  await page.dispose();
});

test('redaction covers repeated private credentials without changing safe text', () => {
  assert.equal(redact('safe token / token', ['token']), 'safe [REDACTED] / [REDACTED]');
  assert.equal(redact('safe', []), 'safe');
});

test('a lifecycle child uses private IPC, pipe capture, and serial ownership', async () => {
  const fixture = fakeForkFactory();
  const invocation = new ChildInvocation('completed', fixture.forkProcess);
  await invocation.started();
  assert.throws(() => new ChildInvocation('completed', fixture.forkProcess), /one at a time/);
  const result = await invocation.execute();
  assert.equal(result.credentialsRedacted, true);
  assert.equal(JSON.stringify(result).includes('private-run-credential'), false);
  assert.deepEqual(fixture.calls[0].spawnOptions.stdio, ['ignore', 'pipe', 'pipe', 'ipc']);
  assert.equal(fixture.calls[0].spawnOptions.env.ACCEPTANCE_RESET_TOKEN, undefined);
  assert.equal(fixture.calls[0].spawnOptions.env.ACCEPTANCE_EVENT_LOG, undefined);
  const next = new ChildInvocation('completed', fixture.forkProcess);
  await next.started();
  await next.execute();
  assert.equal(fixture.maxActive(), 1);
});

test('a normal-suite parent stack blocks lifecycle child creation', () => {
  state.stopped = false;
  try {
    assert.throws(() => new ChildInvocation('completed', fakeForkFactory().forkProcess), /must not own/);
  } finally { state.stopped = true; }
});

test('split stdout and public-message credential leaks fail audit and stay redacted in reports', async () => {
  const fixture = fakeForkFactory({ stdoutLeak: true, publicLeak: true });
  const invocation = new ChildInvocation('completed', fixture.forkProcess);
  await invocation.started();
  const result = await invocation.execute();
  assert.equal(result.credentialsRedacted, false);
  assert.match(result.auditError, /disclosed a run credential/);
  assert.equal(JSON.stringify(result).includes('private-run-credential'), false);
  assert.ok(result.logs.includes('[REDACTED]'));
});

test('two fresh invocations audit teardown before reuse and remove only fixture-owned sentinels', async () => {
  const fixture = fakeForkFactory();
  const docker = fakeDocker();
  const page = new AcceptanceLifecyclePage({}, { forkProcess: fixture.forkProcess, dockerOutput: docker.dockerOutput });
  await page.twoSerialInvocations();
  page.distinctProjects();
  page.singleStartup();
  assert.equal(page.results.length, 2);
  assert.equal(fixture.maxActive(), 1);
  assert.equal(page.report().parentOwnsStack, false);
  await Promise.all([page.dispose(), page.dispose()]);
  assert.equal(docker.removed.length, 3);
  assert.equal(new Set(docker.removed).size, 3, 'Concurrent cleanup deleted a sentinel twice');
  assert.deepEqual([...docker.resources.keys()], ['pre-existing-unrelated-resource']);
  await assert.rejects(page.startIsolated(), /Disposed lifecycle/);
});

test('source-only legacy lifecycle owns no parent stack and runs two real-child invocations', async () => {
  const fixture = fakeForkFactory();
  const docker = fakeDocker();
  const page = new AcceptanceLifecyclePage({}, { forkProcess: fixture.forkProcess, dockerOutput: docker.dockerOutput });
  await page.legacyFreshRun();
  assert.equal(page.results.length, 0);
  await page.legacyScenariosFinish();
  await page.legacyOnlyOwnedRemoved();
  await page.legacyNextFreshRun();
  assert.equal(page.results.length, 2);
  assert.equal(fixture.maxActive(), 1);
  await page.dispose();
});

test('supported cancellation reports the signal and audits owned final cleanup with a single startup', async () => {
  const fixture = fakeForkFactory();
  const docker = fakeDocker();
  const page = new AcceptanceLifecyclePage({ scenarioName: 'Controlled cancellation removes the owned stack' },
    { forkProcess: fixture.forkProcess, dockerOutput: docker.dockerOutput });
  await page.startExecutionInvocation();
  await page.cancelInvocation();
  await page.cancelledCleanup();
  page.singleStartup();
  await page.unrelatedUnchanged();
  await page.dispose();
});

test('published lifecycle events retain audited child timestamps exactly once for gate ordering', async () => {
  const fixture = fakeForkFactory();
  const docker = fakeDocker();
  const page = new AcceptanceLifecyclePage({}, { forkProcess: fixture.forkProcess, dockerOutput: docker.dockerOutput });
  await page.twoSerialInvocations();
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'lifecycle-event-audit-'));
  const previous = process.env.ACCEPTANCE_EVENT_LOG;
  const originalLog = console.log;
  try {
    process.env.ACCEPTANCE_EVENT_LOG = path.join(directory, 'events.ndjson');
    console.log = () => {};
    page.publishAudit();
    page.publishAudit();
    const text = fs.readFileSync(process.env.ACCEPTANCE_EVENT_LOG, 'utf8');
    const events = text.trim().split('\n').map(line => JSON.parse(line));
    assert.deepEqual(events.filter(event => event.type === 'stack-start').map(event => event.at), [100, 200]);
    assert.equal(events.filter(event => event.type === 'lifecycle-invocation-audited').length, 2);
    assert.ok(events.every(event => event.group === 'lifecycle'));
    assert.equal(text.includes('private-run-credential'), false);
  } finally {
    console.log = originalLog;
    if (previous === undefined) delete process.env.ACCEPTANCE_EVENT_LOG;
    else process.env.ACCEPTANCE_EVENT_LOG = previous;
    fs.rmSync(directory, { recursive: true, force: true });
    await page.dispose();
  }
});

test('sentinel deletion refuses ownership changes and never removes pre-existing resources', async () => {
  const docker = fakeDocker();
  const page = new AcceptanceLifecyclePage({}, { dockerOutput: docker.dockerOutput });
  await page.independentValidation();
  const changed = page.sentinel.volume;
  docker.resources.get(changed).Labels['com.docker.compose.project'] = 'someone-else';
  await assert.rejects(page.dispose(), /cleanup\/audit failed/);
  assert.equal(docker.removed.includes(changed), false);
  assert.equal(docker.removed.includes('pre-existing-unrelated-resource'), false);
});

test('cleanup variants complete and audit serially before the next owned invocation', async () => {
  const order = [];
  const page = new AcceptanceLifecyclePage({});
  const invocation = kind => ({ kind, execute: async () => {
    order.push(`execute:${kind}`);
    return { kind, outcome: 'reset-failed', code: 1 };
  } });
  page.current = invocation('cleanup');
  page.startIsolated = async kind => { order.push(`start:${kind}`); page.current = invocation(kind); };
  page.collect = async result => { page.results.push(result); return result; };
  page.failedBoundary = () => { order.push(`closed:${page.results.at(-1).kind}`); };
  page.singleStartup = () => {};
  page.assertResultCleanup = async result => { order.push(`removed:${result.kind}`); };
  page.unrelatedUnchanged = async () => { order.push('sentinel'); };
  await page.requestTerminalReset();
  assert.deepEqual(order, ['execute:cleanup', 'closed:cleanup', 'removed:cleanup', 'sentinel',
    'start:filesystem', 'execute:filesystem', 'closed:filesystem', 'removed:filesystem', 'sentinel',
    'start:partial-controller', 'execute:partial-controller', 'closed:partial-controller', 'removed:partial-controller', 'sentinel']);
});

test('cleanup assertions require all real partial variants and their exact failed phases', () => {
  const page = new AcceptanceLifecyclePage({});
  page.results = ['cleanup', 'filesystem', 'partial-controller'].map(kind => ({ kind,
    diagnostics: { reset: { phase: 'failed', baseline_verified: false,
      failure_phase: kind === 'filesystem' ? 'cleaning_files' : 'cleaning_previews' }, admissionStatus: 503,
      refusedFixtureUnchanged: kind === 'cleanup' ? {} : undefined, partialCleanup: kind !== 'cleanup' ? {} : undefined },
    events: [{ type: 'scenario-start' }] }));
  page.cleanupFailed();
  page.results[1].diagnostics.reset.failure_phase = 'cleaning_previews';
  assert.throws(() => page.cleanupFailed());
  page.results.splice(1, 1);
  assert.throws(() => page.cleanupFailed());
});

test('isolated lifecycle hooks never start a normal parent stack', () => {
  const hooks = fs.readFileSync(path.join(repoRoot, 'acceptance-tests/features/lifecycle/hooks.js'), 'utf8');
  assert.doesNotMatch(hooks, /BeforeAll\(|chromium|startApplication\(/);
});
