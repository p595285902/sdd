const { Given, When, Then } = require('@cucumber/cucumber');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { configureDemoRepository } = require('../features/support/app-lifecycle.js');

async function readyChat(world) {
  await configureDemoRepository(true);
  const token = await world.apiClient.authenticateSuperuser();
  const chat = await world.apiClient.createDevelopmentChat(token, `Preview ${randomUUID()}`);
  const response = await world.apiClient.setupDevelopmentWorkspace(token, chat.id);
  assert.equal(response.status(), 200, await response.text());
  return chat;
}

Given('two Development Chats have separate checkouts of the same repository', async function () {
  this.previewChats = [await readyChat(this), await readyChat(this)];
  await this.apiClient.editWorkspaceFile(this.previewChats[0].id, 'first-only', 'first');
  await this.apiClient.editWorkspaceFile(this.previewChats[1].id, 'second-only', 'second');
});

When('a preview workload starts for each chat', async function () {
  this.previewContainers = await Promise.all(
    this.previewChats.map((chat) => this.previewWorkloadPage.start(chat.id)),
  );
});

Then('each workload uses only its own chat\'s checkout', function () {
  assert.notEqual(this.previewContainers[0].Id, this.previewContainers[1].Id);
  this.previewContainers.forEach((container, index) => {
    this.previewWorkloadPage.expectOnlyCheckout(container, this.previewChats[index].id);
  });
  assert.ok(this.previewWorkloadPage.canRead(this.previewContainers[0], 'first-only'));
  assert.ok(this.previewWorkloadPage.canRead(this.previewContainers[1], 'second-only'));
});

Then('neither workload can read the other chat\'s checkout', function () {
  this.previewWorkloadPage.cannotRead(this.previewContainers[0], 'second-only');
  this.previewWorkloadPage.cannotRead(this.previewContainers[1], 'first-only');
});

Given('a Development Chat has a ready checkout', async function () {
  this.previewChats = [await readyChat(this)];
});

When('its preview workload starts', async function () {
  this.previewContainers = [await this.previewWorkloadPage.start(this.previewChats[0].id)];
});

Then('the workload has resource limits and no backend credentials', function () {
  this.previewWorkloadPage.expectSandbox(this.previewContainers[0]);
});

Then('it has no host control socket or publicly published service port', function () {
  this.previewWorkloadPage.expectOnlyCheckout(this.previewContainers[0], this.previewChats[0].id);
  this.previewWorkloadPage.expectSandbox(this.previewContainers[0]);
});