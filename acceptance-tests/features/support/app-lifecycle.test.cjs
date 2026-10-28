const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const { EventEmitter } = require('node:events');
const { mock, test } = require('node:test');

const calls = [];
let container;
let failRecreation = false;
let failingHealthProbes = 0;
let nextId = 0;

mock.method(childProcess, 'spawn', (command, args, options) => {
  const child = new EventEmitter();
  calls.push({ command, args, env: options.env });
  process.nextTick(() => {
    if (args.includes('--force-recreate') && failRecreation) {
      child.emit('exit', 1);
      return;
    }
    if (args.includes('backend') && args.includes('up')) {
      container = {
        Id: `backend-${++nextId}`,
        State: { Running: true, Health: { Status: 'healthy' } },
        Config: {
          Env: [
            `DEMO_GITHUB_REPO=${options.env.DEMO_GITHUB_REPO}`,
            `DEMO_GITHUB_TOKEN=${options.env.DEMO_GITHUB_TOKEN}`,
          ],
        },
      };
    }
    if (args.includes('down')) container = null;
    child.emit('exit', 0);
  });
  return child;
});

mock.method(childProcess, 'execFile', (command, args, options, callback) => {
  const stdout = args.includes('ps') ? (container?.Id ?? '') : JSON.stringify(container);
  process.nextTick(() => callback(null, stdout, ''));
});

mock.method(globalThis, 'fetch', async () => ({
  ok: failingHealthProbes-- <= 0,
}));

const {
  configureDemoRepository,
  startApplication,
  state,
  stopApplication,
} = require('./app-lifecycle.js');

test('reuses healthy configured backend, applies transitions, and recovers after failure', async () => {
  await startApplication();
  assert.equal(state.demoRepositoryAvailable, true);
  assert.equal(state.projectName, `sdd-acceptance-${process.pid}`);
  assert.equal(state.env.DEMO_GITHUB_REPO, 'https://example.com/acceptance/demo-repository.git');
  const originalId = state.backendId;

  await configureDemoRepository(true);
  await configureDemoRepository(true);
  assert.equal(state.backendId, originalId);
  assert.equal(state.backendRecreations, 0);

  await configureDemoRepository(false);
  assert.notEqual(state.backendId, originalId);
  assert.equal(container.Config.Env[0], 'DEMO_GITHUB_REPO=');
  await configureDemoRepository(true);
  assert.equal(state.backendRecreations, 2);
  await configureDemoRepository(true);
  assert.equal(state.backendRecreations, 2);

  container.Id = 'unexpected-replacement';
  await configureDemoRepository(true);
  assert.equal(state.backendRecreations, 3);

  container.State.Health.Status = 'unhealthy';
  await configureDemoRepository(true);
  assert.equal(state.backendRecreations, 4);

  failingHealthProbes = 1;
  await configureDemoRepository(true);
  assert.equal(state.backendRecreations, 5);

  failRecreation = true;
  await assert.rejects(configureDemoRepository(false), /exited with code 1/);
  assert.equal(state.demoRepositoryAvailable, undefined);
  assert.equal(state.backendId, undefined);
  failRecreation = false;
  await configureDemoRepository(false);
  assert.equal(state.demoRepositoryAvailable, false);
  await stopApplication();
  assert.equal(container, null);
  const down = calls.find(({ args }) => args.includes('down'));
  assert.ok(down.args.includes(state.projectName));
  assert.ok(down.args.includes('--volumes'));
  assert.ok(down.args.includes('--remove-orphans'));
  assert.ok(calls.every(({ args }) => args.includes(state.projectName) || args.includes('prestart.sh')));
});
