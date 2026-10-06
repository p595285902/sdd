const { Given, When, Then } = require('@cucumber/cucumber');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { configureDemoRepository } = require('../features/support/app-lifecycle.js');

async function chatWithInstructions(world, kind) {
  await configureDemoRepository(true);
  const token = await world.apiClient.authenticateSuperuser();
  const chat = await world.apiClient.createDevelopmentChat(token, `Instructions ${randomUUID()}`);
  const setup = await world.apiClient.setupDevelopmentWorkspace(token, chat.id);
  assert.equal(setup.status(), 200, await setup.text());
  await world.previewWorkloadPage.prepareInstructions(chat.id, kind);
  return chat;
}

Given('a Development Chat checkout has a root README documenting dependency setup and non-Compose website and API startup commands with distinct localhost ports', async function () {
  this.instructionChat = await chatWithInstructions(this, 'website');
});

Given('a Development Chat has documented non-Compose website and API commands that require local dependencies', async function () {
  this.instructionChat = await chatWithInstructions(this, 'website');
});

Given('a Development Chat has documented startup commands that do not become ready before the configured timeout', async function () {
  this.instructionChat = await chatWithInstructions(this, 'timeout');
  this.otherInstructionChat = await chatWithInstructions(this, 'website');
  await this.previewWorkloadPage.start(this.otherInstructionChat.id);
});

Given('a Development Chat checkout has no startup commands in its root README', async function () {
  this.instructionChat = await chatWithInstructions(this, 'missing');
});

Given('a Development Chat checkout has a root README documenting only Docker Compose startup', async function () {
  this.instructionChat = await chatWithInstructions(this, 'compose');
});

When('startup instructions are resolved and executed for that chat', async function () {
  await this.previewWorkloadPage.selectInstructions(this.previewWorkloadPage.documentedPlan());
  await this.previewWorkloadPage.launch(this.instructionChat.id);
});

When('its dependency setup and both servers run in the private workload', async function () {
  await this.previewWorkloadPage.selectInstructions(this.previewWorkloadPage.documentedPlan());
  await this.previewWorkloadPage.launch(this.instructionChat.id);
});

When('those commands run in its private workload', async function () {
  await this.previewWorkloadPage.selectInstructions(this.previewWorkloadPage.documentedPlan());
  await this.previewWorkloadPage.launch(this.instructionChat.id);
});

When('startup instructions are resolved for that chat', async function () {
  await this.previewWorkloadPage.selectInstructions(null);
  await this.previewWorkloadPage.launch(this.instructionChat.id);
});

When('the user provides startup instructions', async function () {
  await this.previewWorkloadPage.prepareInstructions(this.instructionChat.id, 'website');
  await this.previewWorkloadPage.selectInstructions(this.previewWorkloadPage.documentedPlan());
  await this.previewWorkloadPage.launch(this.instructionChat.id, 'Run the website and API as documented in the updated README.');
});

Then('the documented dependencies are installed and both documented services respond on their selected localhost ports inside that chat\'s workload', function () {
  assert.equal(this.previewWorkloadPage.lastLaunch.status, 200);
  assert.equal(this.previewWorkloadPage.installedDependency(this.instructionChat.id), true);
  assert.match(this.previewWorkloadPage.serviceResponse(this.instructionChat.id, 8765), /API reachable true/);
  assert.match(this.previewWorkloadPage.serviceResponse(this.instructionChat.id, 8766), /API response/);
});

Then('no additional command approval is required', function () {
  assert.equal(this.previewWorkloadPage.lastLaunch.body.state, 'running');
});

Then('the website can reach its API on localhost inside that workload', function () {
  assert.match(this.previewWorkloadPage.serviceResponse(this.instructionChat.id, 8765), /API reachable true/);
});

Then('neither service has a published host port or access to backend secrets', function () {
  const container = JSON.parse(this.previewWorkloadPage.docker('inspect', this.previewWorkloadPage.containerIds(this.instructionChat.id)[0]))[0];
  this.previewWorkloadPage.expectSandbox(container);
  this.previewWorkloadPage.expectPreviewTools(this.instructionChat.id);
  this.previewWorkloadPage.expectNoExternalNetwork(this.instructionChat.id);
});

Then('startup fails with a redacted diagnostic visible in that chat', async function () {
  assert.equal(this.previewWorkloadPage.lastLaunch.status, 502);
  assert.match(this.previewWorkloadPage.lastLaunch.body.detail, /startup failed or timed out/i);
  const status = await this.previewWorkloadPage.contextStatus(this.instructionChat.id);
  assert.equal(status.body.state, 'failed');
});

Then('its startup processes are stopped without affecting another chat\'s workload', function () {
  assert.equal(this.previewWorkloadPage.isRunning(this.instructionChat.id), false);
  assert.equal(this.previewWorkloadPage.isRunning(this.otherInstructionChat.id), true);
});

Then('the user is asked in chat for a command or a pointer to instructions', async function () {
  assert.equal(this.previewWorkloadPage.lastLaunch.body.state, 'needs_instructions');
  const messages = await this.apiClient.listDevelopmentMessages(this.apiClient.superuserToken, this.instructionChat.id);
  assert.ok(messages.data.some((message) => message.role === 'assistant' && message.content.includes('checkout-local pointer')));
});

Then('no undocumented command is executed', function () {
  assert.equal(this.previewWorkloadPage.isRunning(this.instructionChat.id), false);
});

Then('those instructions are used only for that chat\'s preview', async function () {
  assert.equal(this.previewWorkloadPage.lastLaunch.body.state, 'running');
  assert.equal(this.previewWorkloadPage.installedDependency(this.instructionChat.id), true);
  const other = await chatWithInstructions(this, 'missing');
  await this.previewWorkloadPage.selectInstructions(null);
  await this.previewWorkloadPage.launch(other.id);
  assert.equal(this.previewWorkloadPage.lastLaunch.body.state, 'needs_instructions');
  assert.equal(this.previewWorkloadPage.isRunning(other.id), false);
});

Then('the user is asked in chat for non-Compose startup commands or a checkout-local pointer', async function () {
  assert.equal(this.previewWorkloadPage.lastLaunch.body.state, 'needs_instructions');
  assert.match(this.previewWorkloadPage.lastLaunch.body.message, /non-Compose/);
});

Then('no Compose command is executed', function () {
  assert.equal(this.previewWorkloadPage.isRunning(this.instructionChat.id), false);
});