'use strict';
const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { mock, test } = require('node:test');

let calls = [];
let requests = [];
let controls;
let resetFailure;
let badAck;
let removalFailure;
let stateFailure;
let configurationFailure;
let misappliedConfiguration;
let startupFailure;
let mirrors = [];
let previews = { containers: [], networks: [], volumes: [], images: [] };
mock.method(childProcess, 'spawn', (command, args, options) => {
  const child = Object.assign(new EventEmitter(), { stdout: new PassThrough(), stderr: new PassThrough() });
  calls.push({ command, args, env: options.env, timeout: options.timeout, killSignal: options.killSignal });
  process.nextTick(() => {
    if (args.includes('up') && args.includes('backend')) {
      if (startupFailure) {
        child.stdout.end(); child.stderr.end(); child.emit('close', 1);
        return;
      }
      controls = { run_id: options.env.ACCEPTANCE_RUN_ID, generation: 0, phase: 'admitting', configuration: 'available', baseline_verified: false, active_work: {}, timing: { timeout_seconds: 15, grace_seconds: 0.3 } };
    }
    child.stdout.end(); child.stderr.end(); child.emit('close', 0);
  });
  return child;
});
mock.method(childProcess, 'execFile', (_command, args, _options, callback) => {
  let output = args[0] === 'info' ? JSON.stringify(mirrors) : '';
  assert.notEqual(args[0], 'inspect', 'Lifecycle must not collect Docker identity snapshots');
  assert.ok(!(args.includes('compose') && args.includes('ps')), 'Lifecycle must not discover snapshot container IDs');
  if (args.includes('--filter') && args.at(-1).includes('sdd.preview.project=')) {
    const kind = args[0] === 'ps' ? 'containers' : args[0] === 'network' ? 'networks' : args[0] === 'volume' ? 'volumes' : 'images';
    output = previews[kind].join('\n');
  } else if (args.includes('rm')) {
    if (removalFailure) {
      removalFailure = false;
      calls.push({ command: 'docker', args });
      process.nextTick(() => callback(new Error('Fixture dynamic cleanup failure'), '', ''));
      return;
    }
    const kind = args[0] === 'rm' ? 'containers' : args[0] === 'network' ? 'networks' : args[0] === 'volume' ? 'volumes' : 'images';
    previews[kind] = previews[kind].filter(id => id !== args.at(-1));
  }
  calls.push({ command: 'docker', args });
  process.nextTick(() => callback(null, output, ''));
});
mock.method(globalThis, 'fetch', async (url, options = {}) => {
  const data = options.body ? JSON.parse(options.body) : undefined;
  requests.push({ url, data, headers: options.headers });
  if (url.includes('health-check')) return { ok: true };
  if (url.endsWith('state') && stateFailure) {
    return { ok: stateFailure !== 'http', status: 503, json: async () => ({ ...controls, run_id: 'wrong-run' }) };
  }
  if (url.endsWith('configuration')) {
    if (configurationFailure) return { ok: false, status: 503, json: async () => ({}) };
    if (!misappliedConfiguration) controls.configuration = data.mode;
  }
  if (url.endsWith('reset')) {
    if (resetFailure) {
      controls.phase = 'failed'; controls.failure_phase = resetFailure;
      return { ok: false, status: 504, json: async () => ({ detail: 'Acceptance reset failed' }) };
    }
    controls.generation++; controls.phase = 'ready'; controls.baseline_verified = true; controls.configuration = 'available';
    return { ok: true, status: 200, json: async () => ({ ...controls, reset_id: data.reset_id, ...(badAck || {}) }) };
  }
  return { ok: true, status: 200, json: async () => ({ ...controls }) };
});
const app = require('./app-lifecycle.js');
async function fresh(options = {}) {
  mirrors = options.mirrors || [];
  calls = []; requests = []; resetFailure = undefined; badAck = undefined;
  removalFailure = false; stateFailure = undefined; configurationFailure = false;
  misappliedConfiguration = false; startupFailure = false;
  previews = { containers: [], networks: [], volumes: [], images: [] };
  await app.startApplication();
}
function assertNoSnapshots() {
  for (const key of ['stackSnapshot', 'verifyStack', 'backendInfo']) assert.equal(Object.hasOwn(app, key), false);
  for (const key of ['initialSnapshot', 'backendId', 'backendRecreations']) assert.equal(Object.hasOwn(app.state, key), false);
  assert.ok(calls.every(call => call.args[0] !== 'inspect' && !(call.args.includes('compose') && call.args.includes('ps'))));
  assert.equal(requests.filter(request => request.url.includes('health-check')).length, 1, 'Only startup checks HTTP readiness');
  assert.equal(Object.hasOwn(app.state.events.find(event => event.type === 'stack-ready'), 'identity'), false);
}
async function assertClosed() {
  const count = requests.length;
  await assert.rejects(app.resetScenarioState(), /already failed/);
  await assert.rejects(app.configureDemoRepository(true), /closed/);
  assert.equal(requests.length, count);
  assert.ok(!calls.some(call => call.args.includes('--force-recreate')));
}

test('one stack starts with bounded readiness and no initial or later identity snapshot', async () => {
  await fresh();
  assert.match(app.state.projectName, /^sdd-acceptance-\d+-[a-f0-9]{8}$/);
  assert.equal(app.state.env.COMPOSE_PROJECT_NAME, app.state.projectName);
  assert.ok(calls.filter(call => call.env).every(call => call.timeout === 180_000 && call.killSignal === 'SIGKILL'));
  assert.ok(calls.some(call => call.args.includes('up') && call.args.includes('--wait')));
  const count = calls.length;
  await assert.rejects(app.startApplication(), /cannot start a second stack/);
  assert.equal(calls.length, count);
  await app.configureDemoRepository(true);
  await app.resetScenarioState();
  assertNoSnapshots();
  await app.stopApplication();
});
test('test-only cache overlays follow the host mirror and disappear after teardown', async () => {
  const fs = require('node:fs');
  await fresh({ mirrors: ['http://127.0.0.1:5001/'] });
  const cache = app.state.previewCache;
  assert.equal(cache.upstream, 'http://host.docker.internal:5001');
  assert.equal(app.state.env.ACCEPTANCE_PREVIEW_DOCKERFILE, cache.controllerDockerfile);
  assert.equal(app.state.env.ACCEPTANCE_NATIVE_DOCKERFILE, cache.nativeDockerfile);
  assert.ok(fs.existsSync(cache.controllerDockerfile));
  assert.ok(app.state.events.some(event => event.type === 'preview-cache-enabled'));
  assertNoSnapshots();
  await app.stopApplication();
  assert.equal(fs.existsSync(cache.directory), false);
});

test('no configured mirror leaves production image definitions unchanged', async () => {
  await fresh();
  assert.equal(app.state.previewCache, undefined);
  assert.equal(app.state.env.ACCEPTANCE_PREVIEW_DOCKERFILE, undefined);
  assert.equal(app.state.env.ACCEPTANCE_NATIVE_DOCKERFILE, undefined);
  await app.stopApplication();
});

test('browser and preview use separate same-site loopback origins at the published port', async () => {
  await fresh();
  const base = new URL(app.state.baseUrl);
  const browser = new URL(app.state.browserBaseUrl);
  const preview = new URL(app.state.env.PREVIEW_ORIGIN);
  assert.equal(base.hostname, '127.0.0.1');
  assert.equal(browser.hostname, 'app.localhost');
  assert.equal(preview.hostname, `preview.${browser.hostname}`);
  assert.notEqual(browser.origin, preview.origin);
  assert.equal(preview.protocol, base.protocol);
  assert.equal(browser.protocol, base.protocol);
  assert.equal(preview.port, base.port);
  assert.equal(browser.port, base.port);
  assert.equal(app.state.env.ACCEPTANCE_PORT, base.port);
  assert.equal(app.state.env.FRONTEND_HOST, browser.origin);
  assert.ok(calls.filter(call => call.env).every(call =>
    call.env.PREVIEW_ORIGIN === preview.origin && call.env.FRONTEND_HOST === browser.origin));
  await app.stopApplication();
});

test('configuration overrides verify effective control state without inspecting or recreating containers', async () => {
  await fresh();
  await app.configureDemoRepository(false);
  assert.equal((await app.controlState()).configuration, 'unavailable');
  assert.equal(app.state.env.DEMO_GITHUB_REPO, 'https://example.com/acceptance/demo-repository.git');
  await app.configureDemoRepository(true);
  await app.configureDemoRepository(true);
  assert.equal((await app.controlState()).configuration, 'available');
  assert.ok(!calls.some(call => call.args.includes('--force-recreate')));
  assert.equal(requests.filter(request => request.url.endsWith('configuration')).length, 2);
  assert.ok(app.state.events.filter(event => event.type === 'configuration').every(event => Number.isFinite(event.milliseconds) && event.milliseconds >= 0));
  assertNoSnapshots();
  await app.stopApplication();
});
test('verified resets publish successive generations without starting another stack or taking snapshots', async () => {
  await fresh();
  for (const generation of [1, 2]) {
    const ack = await app.resetScenarioState();
    assert.equal(ack.generation, generation);
    assert.equal(ack.baseline_verified, true);
  }
  assert.equal(app.state.events.filter(event => event.type === 'stack-start').length, 1);
  const resets = requests.filter(request => request.url.endsWith('reset'));
  assert.deepEqual(resets.map(request => request.data.expected_generation), [0, 1]);
  assert.notEqual(resets[0].data.reset_id, resets[1].data.reset_id);
  assert.equal(resets[0].headers.Authorization, `Bearer ${app.state.resetToken}`);
  assert.equal(resets[0].headers['X-Acceptance-Run'], app.state.projectName);
  assert.ok(!JSON.stringify(app.state.events).includes(app.state.resetToken));
  assertNoSnapshots();
  await app.stopApplication();
});
test('unverified control state closes the invocation before reset mutation', async () => {
  for (const invalid of ['http', 'run']) {
    await fresh(); stateFailure = invalid;
    await assert.rejects(app.resetScenarioState(), /control state could not be verified/);
    assert.equal(requests.filter(request => request.url.endsWith('reset')).length, 0);
    assert.equal(app.state.events.at(-1).phase, 'control');
    await assertClosed();
    await app.stopApplication();
  }
});
test('failed or unapplied configuration overrides remain fatal', async () => {
  for (const failure of ['http', 'unapplied']) {
    await fresh();
    configurationFailure = failure === 'http';
    misappliedConfiguration = failure === 'unapplied';
    await assert.rejects(app.configureDemoRepository(false), /configuration verification failed|configuration was not applied/);
    assert.equal(app.state.events.at(-1).type, 'configuration-failed');
    await assertClosed();
    await app.stopApplication();
  }
});
test('reset failure reports actual failed phase and final teardown stops producers first', async () => {
  await fresh(); resetFailure = 'quiescing';
  previews = { containers: ['owned-container'], networks: ['owned-network'], volumes: ['owned-volume'], images: ['owned-image'] };
  await assert.rejects(app.resetScenarioState(), /quiescing/);
  assert.equal(app.state.events.at(-1).phase, 'quiescing');
  await assertClosed();
  await app.stopApplication();
  const stop = calls.findIndex(call => call.args.includes('stop'));
  const remove = calls.findIndex(call => call.args[0] === 'rm');
  const down = calls.findIndex(call => call.args.includes('down'));
  assert.ok(stop >= 0 && remove > stop && down > remove);
  assert.equal(app.state.stopped, true);
  assert.equal(app.state.events.at(-1).ownedResourcesEmpty, true);
});
test('dynamic cleanup failure still tears down Compose and reports failure after final owned audit', async () => {
  await fresh();
  previews.containers = ['owned-container'];
  removalFailure = true;
  await assert.rejects(app.stopApplication(), /final teardown encountered a failure/);
  assert.ok(calls.some(call => call.args.includes('down')));
  assert.equal(app.state.stopped, true);
  assert.deepEqual(previews.containers, []);
  assert.equal(app.state.events.at(-1).type, 'teardown-failed');
  assert.equal(app.state.events.at(-1).ownedResourcesEmpty, true);
});
test('success status with an unverified or mismatched acknowledgement is fatal', async () => {
  for (const invalid of [{ baseline_verified: false }, { generation: 19 }, { run_id: 'wrong-run' }, { reset_id: 'wrong-reset' }, { phase: 'resetting' }]) {
    await fresh(); badAck = invalid;
    await assert.rejects(app.resetScenarioState(), /reset failed/);
    assert.ok(app.state.fatal);
    assert.equal(app.state.generation, 0);
    await assertClosed();
    await app.stopApplication();
  }
});
test('a new invocation uses a new run credential and project; redaction covers declared secrets', async () => {
  await fresh();
  const project = app.state.projectName, token = app.state.resetToken;
  assert.equal(app.redact(`${token} ${app.state.env.DEMO_GITHUB_TOKEN}`), '[redacted] [redacted]');
  await app.stopApplication();
  await fresh();
  assert.notEqual(app.state.projectName, project);
  assert.notEqual(app.state.resetToken, token);
  await app.stopApplication();
});
test('startup command failure still tears down the owned stack without collecting identities', async () => {
  await fresh();
  await app.stopApplication();
  calls = []; requests = []; startupFailure = true;
  await assert.rejects(app.startApplication(), /command exited with code 1/);
  assert.ok(calls.some(call => call.args.includes('down')));
  assert.equal(app.state.stopped, true);
  assert.equal(app.state.events.at(-1).ownedResourcesEmpty, true);
  assert.equal(app.state.events.some(event => event.type === 'stack-ready'), false);
});
