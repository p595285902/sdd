const { Given, When, Then } = require('@cucumber/cucumber');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { configureDemoRepository } = require('../features/support/app-lifecycle.js');

Given('a Development Chat has a ready checkout and resolved startup instructions', async function () {
  await configureDemoRepository(true);
  const token = await this.apiClient.authenticateSuperuser();
  this.startupChat = await this.apiClient.createDevelopmentChat(token, `Startup ${randomUUID()}`);
  const response = await this.apiClient.setupDevelopmentWorkspace(token, this.startupChat.id);
  assert.equal(response.status(), 200, await response.text());
  await this.previewWorkloadPage.prepareInstructions(this.startupChat.id, 'website');
  await this.previewWorkloadPage.selectInstructions(this.previewWorkloadPage.documentedPlan());
});

Given('a documented Compose file requests host networking or a Docker socket mount', async function () {
  this.unsafeComposeFixture = true;
  await configureDemoRepository(true);
  const token = await this.apiClient.authenticateSuperuser();
  this.startupChat = await this.apiClient.createDevelopmentChat(token, `Unsafe Compose ${randomUUID()}`);
  const response = await this.apiClient.setupDevelopmentWorkspace(token, this.startupChat.id);
  assert.equal(response.status(), 200, await response.text());
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'README.md',
    'Start the website with docker compose -f compose.yml up website.');
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'compose.yml',
    'services:\n  website:\n    image: python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88\n    command: ["python", "-m", "http.server", "8765"]\n    expose: [8765]\n    network_mode: host\n');
});

Given('a Development Chat checkout has a README describing an existing Compose file with website and API services', async function () {
  await configureDemoRepository(true);
  const token = await this.apiClient.authenticateSuperuser();
  this.startupChat = await this.apiClient.createDevelopmentChat(token, `Compose ${randomUUID()}`);
  const response = await this.apiClient.setupDevelopmentWorkspace(token, this.startupChat.id);
  assert.equal(response.status(), 200, await response.text());
  await this.previewWorkloadPage.prepareCompose(this.startupChat.id);
});

Then('the website and API start in that chat\'s private Compose project', { timeout: 150000 }, async function () {
  assert.equal(this.startupResponse.body.state, 'ready');
  assert.equal(this.startupResponse.body.website_port, '8765');
  assert.equal(this.previewWorkloadPage.composeContainers(this.startupChat.id).length, 2);
  assert.match(this.previewWorkloadPage.serviceResponse(this.startupChat.id, 8765), /API reachable/);
  await this.previewWorkloadPage.prepareComposeDependencies(this.startupChat.id);
  await this.previewWorkloadPage.restartCompose(this.startupChat.id, 200, 120000);
  assert.equal(this.previewWorkloadPage.composeContainers(this.startupChat.id).length, 2);
  assert.match(this.previewWorkloadPage.serviceResponse(this.startupChat.id, 8765), /API reachable/);
});

Then('another chat with the same repository uses a different Compose project', async function () {
  const token = this.apiClient.superuserToken;
  const other = await this.apiClient.createDevelopmentChat(token, `Compose other ${randomUUID()}`);
  const response = await this.apiClient.setupDevelopmentWorkspace(token, other.id);
  assert.equal(response.status(), 200, await response.text());
  await this.previewWorkloadPage.prepareCompose(other.id);
  const started = await this.previewWorkloadPage.openContext(other.id);
  assert.equal(started.body.state, 'ready');
  assert.notEqual(this.previewWorkloadPage.composeNetwork(other.id),
    this.previewWorkloadPage.composeNetwork(this.startupChat.id));
});

Given('a Development Chat checkout has a documented Compose website that depends on an API', async function () {
  await configureDemoRepository(true);
  const token = await this.apiClient.authenticateSuperuser();
  this.startupChat = await this.apiClient.createDevelopmentChat(token, `Network ${randomUUID()}`);
  assert.equal((await this.apiClient.setupDevelopmentWorkspace(token, this.startupChat.id)).status(), 200);
  await this.previewWorkloadPage.prepareCompose(this.startupChat.id);
});

When('the chat\'s private Compose project starts', async function () {
  this.startupResponse = await this.previewWorkloadPage.openContext(this.startupChat.id);
  if (this.startupResponse.body.state !== 'ready') {
    console.error(this.previewWorkloadPage.controllerLogs());
  }
  assert.equal(this.startupResponse.body.state, 'ready');
});

Then('the website can reach its API by service name within that chat\'s network', function () {
  assert.match(this.previewWorkloadPage.serviceResponse(this.startupChat.id, 8765), /API reachable/);
});

Then('neither service can reach the host, backend or another chat\'s private network', async function () {
  const token = this.apiClient.superuserToken;
  const other = await this.apiClient.createDevelopmentChat(token, `Isolated ${randomUUID()}`);
  assert.equal((await this.apiClient.setupDevelopmentWorkspace(token, other.id)).status(), 200);
  await this.previewWorkloadPage.prepareCompose(other.id);
  assert.equal((await this.previewWorkloadPage.openContext(other.id)).body.state, 'ready');
  this.previewWorkloadPage.assertComposeIsolation(this.startupChat.id, other.id);
});

Given('a documented Compose website depends on a service with a host mount or public port', async function () {
  await configureDemoRepository(true);
  const token = await this.apiClient.authenticateSuperuser();
  this.startupChat = await this.apiClient.createDevelopmentChat(token, `Dependency ${randomUUID()}`);
  assert.equal((await this.apiClient.setupDevelopmentWorkspace(token, this.startupChat.id)).status(), 200);
  await this.previewWorkloadPage.prepareCompose(this.startupChat.id);
  const image = 'python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88';
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'compose.yml', `services:
  website:
    image: ${image}
    command: ["python", "-m", "http.server", "8765"]
    expose: [8765]
    depends_on: [api]
  api:
    image: ${image}
    command: ["python", "-m", "http.server", "8766"]
    expose: [8766]
    ports: ["8766:8766"]
`);
  this.unsafeComposeFixture = true;
});

Then('the whole Compose project is rejected before any service starts', async function () {
  assert.equal(this.startupResponse.body.state, 'failed');
  await this.previewWorkloadPage.expectRejectedCompose(this.startupChat.id);
  assert.deepEqual(this.previewWorkloadPage.composeContainers(this.startupChat.id), []);
});

Given('a documented Compose service requires a build source outside its checkout or unrestricted network access', async function () {
  await configureDemoRepository(true);
  const token = await this.apiClient.authenticateSuperuser();
  this.startupChat = await this.apiClient.createDevelopmentChat(token, `Build ${randomUUID()}`);
  assert.equal((await this.apiClient.setupDevelopmentWorkspace(token, this.startupChat.id)).status(), 200);
  await this.previewWorkloadPage.prepareCompose(this.startupChat.id);
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'README.md',
    'Run `docker compose -f compose.yml up website` to start the website.');
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'compose.yml', `services:
  website:
    build:
      context: ../outside
      dockerfile: Dockerfile
    command: ["python", "-m", "http.server", "8765"]
    expose: [8765]
`);
  this.unsafeComposeFixture = true;
});

Then('the unsupported build is rejected before any service starts', { timeout: 150000 }, async function () {
  await this.previewWorkloadPage.expectRejectedCompose(this.startupChat.id);
  await this.previewWorkloadPage.prepareCompose(this.startupChat.id);
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'site/Dockerfile',
    'FROM python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88\nRUN curl https://example.com\n');
  await this.previewWorkloadPage.expectRejectedCompose(this.startupChat.id);
  await this.previewWorkloadPage.prepareCompose(this.startupChat.id);
  await this.previewWorkloadPage.introduceUnsafeBuildSymlink(this.startupChat.id);
  await this.previewWorkloadPage.expectRejectedCompose(this.startupChat.id);
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'README.md',
    'Run `docker compose -f compose.yml up website` to start the website.');
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'compose.yml', `services:
  website:
    build:
      context: .git
      dockerfile: Dockerfile
    command: ["python", "-m", "http.server", "8765"]
    expose: [8765]
`);
  await this.previewWorkloadPage.expectRejectedCompose(this.startupChat.id);
  assert.deepEqual(this.previewWorkloadPage.composeContainers(this.startupChat.id), []);
  await this.previewWorkloadPage.removeUnsafeBuildSymlink(this.startupChat.id);
  await this.previewWorkloadPage.prepareDependencyCompose(this.startupChat.id);
  const started = await this.previewWorkloadPage.openContext(this.startupChat.id, 120000);
  assert.equal(started.body.state, 'ready', this.previewWorkloadPage.controllerLogs());
  assert.match(this.previewWorkloadPage.serviceResponse(this.startupChat.id, 8765), /dependency ready/);
  await this.previewWorkloadPage.prepareNpmDependencyCompose(this.startupChat.id);
  await this.previewWorkloadPage.restartCompose(this.startupChat.id, 200, 120000);
  assert.match(this.previewWorkloadPage.nodeServiceResponse(this.startupChat.id, 8765), /dependency ready/);
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'site/Dockerfile',
    'FROM python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88\nRUN curl https://example.com\n');
  await this.previewWorkloadPage.expectRejectedCompose(this.startupChat.id);
});

Then('the user is asked for compatible instructions in that chat', async function () {
  const response = await this.previewWorkloadPage.launch(this.startupChat.id);
  assert.equal(response.body.state, 'needs_instructions');
  assert.match(response.body.message, /compatible checkout-local instructions/);
});

Given('a Development Chat checkout has runnable README commands but no documented Compose file', async function () {
  await configureDemoRepository(true);
  const token = await this.apiClient.authenticateSuperuser();
  this.startupChat = await this.apiClient.createDevelopmentChat(token, `Commands ${randomUUID()}`);
  assert.equal((await this.apiClient.setupDevelopmentWorkspace(token, this.startupChat.id)).status(), 200);
  await this.previewWorkloadPage.prepareInstructions(this.startupChat.id, 'website');
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'README.md',
    'Do not run docker compose -f compose.yml up website. Run npm install in site, then npm run start in site on port 8765. Run python -m http.server 8766 in api on port 8766.');
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'compose.yml',
    'services:\n  website:\n    network_mode: host\n');
  await this.previewWorkloadPage.selectInstructions(this.previewWorkloadPage.documentedPlan());
});

Then('the documented commands run without generating a Compose file', function () {
  assert.equal(this.startupResponse.body.state, 'ready');
  assert.equal(this.previewWorkloadPage.isRunning(this.startupChat.id), true);
  assert.throws(() => this.previewWorkloadPage.docker('network', 'inspect',
    this.previewWorkloadPage.composeNetwork(this.startupChat.id)));
});

Given('two Development Chats have separate running private Compose projects', async function () {
  await configureDemoRepository(true);
  const token = await this.apiClient.authenticateSuperuser();
  this.startupChat = await this.apiClient.createDevelopmentChat(token, `Delete ${randomUUID()}`);
  this.otherComposeChat = await this.apiClient.createDevelopmentChat(token, `Remain ${randomUUID()}`);
  for (const chat of [this.startupChat, this.otherComposeChat]) {
    assert.equal((await this.apiClient.setupDevelopmentWorkspace(token, chat.id)).status(), 200);
    await this.previewWorkloadPage.prepareCompose(chat.id);
    assert.equal((await this.previewWorkloadPage.openContext(chat.id)).body.state, 'ready');
  }
});

When('one chat\'s preview expires or is deleted', async function () {
  await this.previewWorkloadPage.restartCompose(this.startupChat.id);
  assert.equal(this.previewWorkloadPage.composeContainers(this.startupChat.id).length, 2);
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'compose.yml', `services:
  website:
    image: python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88
    depends_on: [api]
    command: ["python", "-m", "http.server", "8767"]
    expose: [8765]
  api:
    image: python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88
    command: ["python", "-m", "http.server", "8766"]
    expose: [8766]
`);
  await this.previewWorkloadPage.restartCompose(this.startupChat.id, 502);
  assert.deepEqual(this.previewWorkloadPage.composeContainers(this.startupChat.id), []);
  assert.throws(() => this.previewWorkloadPage.composeNetworkDetails(this.startupChat.id));
  assert.match(this.previewWorkloadPage.serviceResponse(this.otherComposeChat.id, 8765), /API reachable/);
  await this.previewWorkloadPage.prepareCompose(this.startupChat.id);
  assert.equal((await this.previewWorkloadPage.openContext(this.startupChat.id)).body.state, 'ready');
  this.previewWorkloadPage.expireCompose(this.startupChat.id);
  assert.deepEqual(this.previewWorkloadPage.composeContainers(this.startupChat.id), []);
  assert.throws(() => this.previewWorkloadPage.composeNetworkDetails(this.startupChat.id));
  assert.equal((await this.previewWorkloadPage.openContext(this.startupChat.id)).body.state, 'ready');
  await this.previewWorkloadPage.deleteChat(this.startupChat.id);
});

Then('that chat\'s containers, network and writable storage are removed', function () {
  assert.deepEqual(this.previewWorkloadPage.composeContainers(this.startupChat.id), []);
  assert.deepEqual(this.previewWorkloadPage.composeImages(this.startupChat.id), []);
  assert.throws(() => this.previewWorkloadPage.composeNetworkDetails(this.startupChat.id));
});

Then('the other chat\'s services remain available', function () {
  assert.equal(this.previewWorkloadPage.composeContainers(this.otherComposeChat.id).length, 2);
  assert.match(this.previewWorkloadPage.serviceResponse(this.otherComposeChat.id, 8765), /API reachable/);
});

When('the user opens Context before any file-changing Agent Turn', async function () {
  this.startupResponse = await this.previewWorkloadPage.openContext(this.startupChat.id);
});

Then('that chat\'s original checkout starts for preview', async function () {
  assert.equal(this.startupResponse.status, 200);
  assert.equal(this.startupResponse.body.state, 'ready');
  assert.equal(this.startupResponse.body.initial_port, '8765');
  assert.equal(this.startupResponse.body.initial_path, '/');
  assert.equal(this.previewWorkloadPage.isRunning(this.startupChat.id), true);
  const status = await this.previewWorkloadPage.contextStatus(this.startupChat.id);
  assert.equal(status.body.id, this.startupResponse.body.id);
  const otherUser = await this.apiClient.createUser();
  const otherToken = await this.apiClient.authenticate(otherUser.email, otherUser.password);
  const denied = await this.previewWorkloadPage.contextStatus(this.startupChat.id, otherToken);
  assert.equal(denied.status, 404);
});

Given('a Development Chat has a stopped preview and resolved startup instructions', async function () {
  await configureDemoRepository(true);
  const token = await this.apiClient.authenticateSuperuser();
  this.startupChat = await this.apiClient.createDevelopmentChat(token, `Stopped ${randomUUID()}`);
  const response = await this.apiClient.setupDevelopmentWorkspace(token, this.startupChat.id);
  assert.equal(response.status(), 200, await response.text());
  await this.previewWorkloadPage.prepareInstructions(this.startupChat.id, 'website');
  assert.equal((await this.previewWorkloadPage.contextStatus(this.startupChat.id)).body.state, 'stopped');
});

When('an Agent Turn completes after changing a non-ignored source file', async function () {
  await this.previewWorkloadPage.completedTurn(this.startupChat.id, 'site/feature.js');
});

Then('that chat\'s preview starts', async function () {
  this.startupResponse = await this.previewWorkloadPage.openContext(this.startupChat.id);
  if (!this.unsafeComposeFixture) {
    if (this.startupResponse.body.state !== 'ready') {
      console.error(this.previewWorkloadPage.controllerLogs());
    }
    assert.equal(this.startupResponse.body.state, 'ready');
    assert.equal(this.previewWorkloadPage.isRunning(this.startupChat.id), true);
  }
});

Then('the unsafe preview configuration is rejected', async function () {
  assert.equal(this.startupResponse.body.state, 'failed');
  await this.previewWorkloadPage.expectRejectedCompose(this.startupChat.id);
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'compose.yml',
    'services:\n  website:\n    image: ${UNAPPROVED_IMAGE}\n    command: ["python", "-m", "http.server", "8765"]\n');
  await this.previewWorkloadPage.expectRejectedCompose(this.startupChat.id);
});

Then('no host resource is exposed to the preview', function () {
  assert.deepEqual(this.previewWorkloadPage.containerIds(this.startupChat.id), []);
});

Given('a Development Chat has a healthy running preview', async function () {
  await configureDemoRepository(true);
  const token = await this.apiClient.authenticateSuperuser();
  this.startupChat = await this.apiClient.createDevelopmentChat(token, `Running ${randomUUID()}`);
  const response = await this.apiClient.setupDevelopmentWorkspace(token, this.startupChat.id);
  assert.equal(response.status(), 200, await response.text());
  await this.previewWorkloadPage.prepareInstructions(this.startupChat.id, 'website');
  await this.previewWorkloadPage.selectInstructions(this.previewWorkloadPage.documentedPlan());
  this.startupResponse = await this.previewWorkloadPage.openContext(this.startupChat.id);
  assert.equal(this.startupResponse.body.state, 'ready');
});

When('an Agent Turn completes after changing only ignored files', async function () {
  await this.previewWorkloadPage.completedTurn(this.startupChat.id, '.claude/notes.md');
});

Then('its running preview remains available for hot reload', async function () {
  const result = await this.previewWorkloadPage.contextStatus(this.startupChat.id);
  assert.equal(result.body.state, 'ready');
  assert.equal(result.body.id, this.startupResponse.body.id);
  assert.match(this.previewWorkloadPage.serviceResponse(this.startupChat.id, 8765), /API reachable true/);
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'api/index.html', 'Live source update');
  await this.previewWorkloadPage.waitForServiceResponse(this.startupChat.id, 8766, 'Live source update');
  assert.equal((await this.previewWorkloadPage.contextStatus(this.startupChat.id)).body.id, result.body.id);
});

Given('a Development Chat has an API-only checkout with documented Swagger startup', async function () {
  await configureDemoRepository(true);
  const token = await this.apiClient.authenticateSuperuser();
  this.startupChat = await this.apiClient.createDevelopmentChat(token, `API ${randomUUID()}`);
  const response = await this.apiClient.setupDevelopmentWorkspace(token, this.startupChat.id);
  assert.equal(response.status(), 200, await response.text());
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'README.md',
    'Run python -m http.server 8766 in api on port 8766. Swagger UI is at /docs.');
  await this.apiClient.editWorkspaceFile(this.startupChat.id, 'api/docs', 'Swagger UI');
  await this.previewWorkloadPage.selectInstructions({
    setup: [], website: null,
    api: { cwd: 'api', argv: ['python', '-m', 'http.server', '8766'], port: 8766, path: '/' },
  });
});

When('that chat\'s preview becomes ready', async function () {
  this.startupResponse = await this.previewWorkloadPage.openContext(this.startupChat.id);
});

Then('the initial preview page is its Swagger page', async function () {
  assert.equal(this.startupResponse.body.state, 'ready');
  assert.equal(this.startupResponse.body.initial_port, '8766');
  assert.equal(this.startupResponse.body.initial_path, '/docs');
  assert.match(this.previewWorkloadPage.serviceResponse(this.startupChat.id, 8766), /directory/i);
});