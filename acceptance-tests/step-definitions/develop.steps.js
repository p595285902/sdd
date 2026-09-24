const { Given, Then, When } = require('@cucumber/cucumber');
const assert = require('node:assert/strict');

Given('an authenticated user is viewing the application', async function () {
  this.userToken = await this.apiClient.authenticateSuperuser();
  await this.developPage.openApplication(this.userToken);
});

When('the user selects Develop from the navigation', async function () {
  await this.developPage.selectDevelop();
});

Then('the Develop workspace is displayed', async function () {
  await this.developPage.expectWorkspaceVisible();
});

Given('an unauthenticated client', function () {});

When('the client requests Development Chats', async function () {
  const api = await this.openApiContext();
  this.response = await api.get('/api/v1/develop/chats');
});

Then('the request is rejected as unauthorized', function () {
  assert.equal(this.response.status(), 401);
});

Given('an authenticated user has opened a new Development Chat', async function () {
  this.userToken = await this.apiClient.authenticateSuperuser();
  this.currentUser = await this.apiClient.currentUser(this.userToken);
  await this.developPage.open(this.userToken);
  await this.developPage.startNewChat();
});

When('the user submits a nonempty first message', async function () {
  this.firstMessage = `Acceptance chat ${Date.now()}`;
  await this.developPage.submitFirstMessage(this.firstMessage);
});

Then('a Development Chat is created for that user', async function () {
  const chats = await this.apiClient.listDevelopmentChats(this.userToken);
  this.developmentChat = chats.data.find((chat) => chat.title === this.firstMessage);
  assert.ok(this.developmentChat);
  assert.equal(this.developmentChat.owner_id, this.currentUser.id);
});

Then('the first message is stored', async function () {
  const messages = await this.apiClient.listDevelopmentMessages(
    this.userToken,
    this.developmentChat.id,
  );
  assert.deepEqual(
    messages.data.map(({ role, content }) => ({ role, content })),
    [{ role: 'user', content: this.firstMessage }],
  );
});