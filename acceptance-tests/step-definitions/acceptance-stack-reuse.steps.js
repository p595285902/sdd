const assert = require('node:assert/strict');
const { execFile } = require('node:child_process');
const { Given, Then, When } = require('@cucumber/cucumber');
const {
  backendInfo,
  configureDemoRepository,
  state,
} = require('../features/support/app-lifecycle.js');

function command(commandName, args, options = {}) {
  return new Promise((resolve, reject) => {
    execFile(commandName, args, options, (error, stdout) => {
      if (error) reject(error);
      else resolve(stdout.trim());
    });
  });
}

async function freshLifecycleRun() {
  const script = `
const { startApplication, state, stopApplication } = require('./features/support/app-lifecycle.js');
(async () => {
  try {
    await startApplication();
    console.log('ACCEPTANCE_PROJECT:' + state.projectName);
  } finally {
    await stopApplication();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
`;
  const output = await command('node', ['-e', script], {
    cwd: __dirname + '/..',
    timeout: 300_000,
    maxBuffer: 10 * 1024 * 1024,
  });
  const project = output.match(/^ACCEPTANCE_PROJECT:(sdd-acceptance-\d+)$/m)?.[1];
  assert.ok(project, 'Fresh lifecycle run did not report its Compose project');
  return project;
}

async function assertProjectRemoved(project) {
  for (const [resource, args] of [
    ['containers', ['ps', '-a', '--filter', `label=com.docker.compose.project=${project}`, '-q']],
    ['networks', ['network', 'ls', '--filter', `label=com.docker.compose.project=${project}`, '-q']],
    ['volumes', ['volume', 'ls', '--filter', `label=com.docker.compose.project=${project}`, '-q']],
  ]) {
    assert.equal(await command('docker', args), '', `Acceptance ${resource} remain for ${project}`);
  }
}

let previousContext;

Given('an acceptance run has a backend with the demo repository configured', async function () {
  await configureDemoRepository(true);
  this.initialBackend = await backendInfo();
  assert.equal(this.initialBackend.healthy, true);
  assert.notEqual(this.context, previousContext);
  previousContext = this.context;
});

When('successive scenarios request that same repository configuration', async function () {
  this.initialRecreations = state.backendRecreations;
  await configureDemoRepository(true);
  await this.apiClient.configureFakeLlm([{ kind: 'text', text: 'scenario state' }]);
  await this.apiClient.resetScenarioState();
  await configureDemoRepository(true);
});

Then('the backend is not recreated between those requests', async function () {
  assert.equal(state.backendRecreations, this.initialRecreations);
  assert.equal((await backendInfo()).id, this.initialBackend.id);
});

Then('each scenario retains its fresh browser context and independent test state', async function () {
  assert.ok(this.context);
  assert.equal(this.page.context(), this.context);
  assert.deepEqual(await this.apiClient.fakeLlmRequests(), []);
  const api = await this.openApiContext();
  const noScript = await api.post('/api/v1/testing/llm/v1/responses', { data: { input: [] } });
  assert.equal(noScript.status(), 500);
});

When('a scenario requests an unconfigured demo repository', async function () {
  await configureDemoRepository(false);
});

Then('that scenario uses a backend with the demo repository unconfigured', async function () {
  const backend = await backendInfo();
  assert.equal(backend.healthy, true);
  assert.equal(backend.repo, '');
  assert.equal(state.demoRepositoryAvailable, false);
  assert.notEqual(backend.id, this.initialBackend.id);
});

When('a later scenario requests the configured demo repository', async function () {
  await configureDemoRepository(true);
  this.restoredBackend = await backendInfo();
  this.restoredRecreations = state.backendRecreations;
});

Then('the later scenario uses a backend with the demo repository configured', function () {
  assert.equal(this.restoredBackend.repo, 'https://example.com/acceptance/demo-repository.git');
  assert.equal(this.restoredBackend.healthy, true);
  assert.equal(state.demoRepositoryAvailable, true);
});

Then('another request for that configuration does not recreate it', async function () {
  await configureDemoRepository(true);
  assert.equal(state.backendRecreations, this.restoredRecreations);
  assert.equal((await backendInfo()).id, this.restoredBackend.id);
});

Given('the default acceptance suite starts a fresh project-scoped stack', function () {
  assert.match(state.projectName, /^sdd-acceptance-\d+$/);
  this.parentProject = state.projectName;
});

When('its scenarios finish', async function () {
  this.finishedProject = await freshLifecycleRun();
});

Then("only that run's project is torn down", async function () {
  await assertProjectRemoved(this.finishedProject);
  assert.notEqual(this.finishedProject, this.parentProject);
  assert.ok(await command('docker', [
    'ps', '--filter', `label=com.docker.compose.project=${this.parentProject}`, '-q',
  ]));
});

Then('a subsequent full-suite run starts a separate fresh project', async function () {
  const nextProject = await freshLifecycleRun();
  assert.notEqual(nextProject, this.finishedProject);
  assert.notEqual(nextProject, this.parentProject);
  await assertProjectRemoved(nextProject);
});
