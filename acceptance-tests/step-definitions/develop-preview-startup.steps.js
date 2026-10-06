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
  const result = await this.previewWorkloadPage.contextStatus(this.startupChat.id);
  assert.equal(result.body.state, 'ready');
  assert.equal(this.previewWorkloadPage.isRunning(this.startupChat.id), true);
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