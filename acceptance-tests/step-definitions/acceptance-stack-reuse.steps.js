const { Given, Then, When } = require('@cucumber/cucumber');

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
When('a scenario requests an unconfigured demo repository', async function () {
  await this.resetPage.unavailableRepository();
});
Then('that scenario uses a backend with the demo repository unconfigured', async function () {
  await this.resetPage.expectUnavailableRepository();
});
When('a later scenario requests the configured demo repository', async function () {
  await this.resetPage.availableRepository();
});
Then('the later scenario uses a backend with the demo repository configured', async function () {
  await this.resetPage.expectAvailableRepository();
});
Then('another request for that configuration does not recreate it', async function () {
  await this.resetPage.anotherRepositoryRequest();
});
