const { Given, Then, When } = require('@cucumber/cucumber');

// Retained for the self-contained complete-command regression fixtures.
Given('an acceptance run has a backend with the demo repository configured', async function () {
  await this.resetPage.configuredRepository();
});
When('successive scenarios request that same repository configuration', async function () {
  await this.resetPage.sameRepositoryRequests();
});
Then('the backend is not recreated between those requests', async function () {
  await this.resetPage.expectNoRecreation();
});
Then('each scenario retains its fresh browser context and independent test state', async function () {
  await this.resetPage.expectIndependentState();
});
Then('that scenario uses a backend with the demo repository unconfigured', async function () {
  await this.resetPage.expectUnavailableRepository();
});
