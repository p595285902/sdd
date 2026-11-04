'use strict';
const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { mock, test } = require('node:test');

let containers = {};
let calls = [];
let requests = [];
let controls;
let resetFailure;
let badAck;
let removalFailure;
let instance = 0;
let previews = { containers: [], networks: [], volumes: [], images: [] };
mock.method(childProcess, 'spawn', (command, args, options) => {
  const child = Object.assign(new EventEmitter(), { stdout: new PassThrough(), stderr: new PassThrough() });
  calls.push({ command, args, env: options.env, timeout: options.timeout, killSignal: options.killSignal });
  process.nextTick(() => {
    if (args.includes('up') && args.includes('backend')) {
      instance++;
      for (const service of ['backend', 'db', 'preview-controller']) {
        containers[service] = {
          Id: `${service}-${instance}`, RestartCount: 0,
          State: { Running: true, StartedAt: 'unchanged-start', Health: { Status: 'healthy' } },
          Mounts: [{ Type: 'volume', Name: `${options.env.COMPOSE_PROJECT_NAME}-${service}-volume`, Destination: `/${service}-data` }],
          Config: { Labels: { 'com.docker.compose.project': options.env.COMPOSE_PROJECT_NAME, 'com.docker.compose.service': service }, Env: Object.entries(options.env).map(([key, value]) => `${key}=${value}`) },
        };
      }
      controls = { run_id: options.env.ACCEPTANCE_RUN_ID, generation: 0, phase: 'admitting', configuration: 'available', boot_id: `boot-${instance}`, baseline_verified: false, active_work: {}, timing: { timeout_seconds: 15, grace_seconds: 0.3 } };
    }
    if (args.includes('down')) containers = {};
    child.stdout.end(); child.stderr.end(); child.emit('close', 0);
  });
  return child;
});
mock.method(childProcess, 'execFile', (_command, args, _options, callback) => {
  let output = '';
  if (args.includes('compose') && args.includes('ps')) output = containers[args.at(-1)]?.Id || '';
  else if (args[0] === 'inspect') output = JSON.stringify(Object.values(containers).find(item => item.Id === args.at(-1)));
  else if (args.includes('--filter') && args.at(-1).includes('sdd.preview.project=')) {
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
  if (url.includes('health-check')) return { ok: true };
  const data = options.body ? JSON.parse(options.body) : undefined;
  requests.push({ url, data, headers: options.headers });
  if (url.endsWith('configuration')) controls.configuration = data.mode;
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
async function fresh() {
  calls = []; requests = []; resetFailure = undefined; badAck = undefined;
  previews = { containers: [], networks: [], volumes: [], images: [] };
  await app.startApplication();
}

test('configuration overrides retain healthy service, boot and volume identities', async () => {
  await fresh();
  const identity = app.state.initialSnapshot;
  assert.match(app.state.projectName, /^sdd-acceptance-\d+-[a-f0-9]{8}$/);
  assert.equal(app.state.env.COMPOSE_PROJECT_NAME, app.state.projectName);
  assert.ok(calls.filter(call => call.env).every(call => call.timeout === 180_000 && call.killSignal === 'SIGKILL'));
  await app.configureDemoRepository(false);
  assert.equal((await app.backendInfo()).repo, '');
  assert.equal(app.state.env.DEMO_GITHUB_REPO, 'https://example.com/acceptance/demo-repository.git');
  await app.configureDemoRepository(true);
  await app.configureDemoRepository(true);
  assert.deepEqual(await app.verifyStack(), identity);
  assert.equal(app.state.backendRecreations, 0);
  assert.ok(!calls.some(call => call.args.includes('--force-recreate')));
  assert.equal(requests.filter(request => request.url.endsWith('configuration')).length, 2);
  assert.ok(app.state.events.filter(event => event.type === 'configuration').every(event => Number.isFinite(event.milliseconds) && event.milliseconds >= 0));
  await app.stopApplication();
});
test('verified reset publishes new generation without starting another stack', async () => {
  await fresh();
  const identity = app.state.initialSnapshot;
  const ack = await app.resetScenarioState();
  assert.equal(ack.generation, 1);
  assert.equal(ack.baseline_verified, true);
  assert.equal(app.state.events.filter(event => event.type === 'stack-start').length, 1);
  assert.deepEqual(await app.verifyStack(), identity);
  const request = requests.find(request => request.url.endsWith('reset'));
  assert.equal(request.headers.Authorization, `Bearer ${app.state.resetToken}`);
  assert.equal(request.headers['X-Acceptance-Run'], app.state.projectName);
  assert.equal(request.data.expected_generation, 0);
  assert.ok(!JSON.stringify(app.state.events).includes(app.state.resetToken));
  await app.stopApplication();
});
test('replacement, restart, mount and boot drift each close the invocation rather than recover', async () => {
  for (const mutate of [
    () => { containers.backend.Id = 'replacement'; },
    () => { containers.db.RestartCount++; },
    () => { containers['preview-controller'].Mounts[0].Name = 'replacement-volume'; },
    () => { controls.boot_id = 'replacement-boot'; },
    () => { containers.backend.State.Health.Status = 'unhealthy'; },
  ]) {
    await fresh(); mutate();
    await assert.rejects(app.configureDemoRepository(false));
    const count = requests.length;
    await assert.rejects(app.resetScenarioState(), /already failed/);
    assert.equal(requests.length, count);
    assert.ok(!calls.some(call => call.args.includes('--force-recreate')));
    await app.stopApplication();
  }
});
test('reset failure reports actual failed phase and final teardown stops producers first', async () => {
  await fresh(); resetFailure = 'quiescing';
  previews = { containers: ['owned-container'], networks: ['owned-network'], volumes: ['owned-volume'], images: ['owned-image'] };
  await assert.rejects(app.resetScenarioState(), /quiescing/);
  assert.equal(app.state.events.at(-1).phase, 'quiescing');
  await assert.rejects(app.configureDemoRepository(true), /closed/);
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
test('success status with an unverified or wrong-generation acknowledgement is fatal', async () => {
  for (const invalid of [{ baseline_verified: false }, { generation: 19 }, { run_id: 'wrong-run' }, { reset_id: 'wrong-reset' }]) {
    await fresh(); badAck = invalid;
    await assert.rejects(app.resetScenarioState(), /reset failed/);
    assert.ok(app.state.fatal);
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
