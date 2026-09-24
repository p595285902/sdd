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