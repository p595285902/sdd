const { Given, Then, When } = require('@cucumber/cucumber');

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