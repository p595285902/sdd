'use strict';
const { Given, Then, When } = require('@cucumber/cucumber');

// Only isolated complete-command validation inventories contain these intents.
Given('an acceptance run has a backend with the demo repository configured', async function () {
  await this.resetPage.configuredRepository();
});
When('successive scenarios request that same repository configuration', async function () {
  await this.resetPage.sameRepositoryRequests();
});
Then('the backend retains the requested demo repository configuration', async function () {
  await this.resetPage.expectConfiguredRepository();
});
Then('each scenario retains its fresh browser context and independent test state', async function () {
  await this.resetPage.expectIndependentState();
});
Then('that scenario uses a backend with the demo repository unconfigured', async function () {
  await this.resetPage.expectUnavailableRepository();
});

When('the isolated command fixture arms a bounded filesystem cleanup fault', async function () {
  await this.resetPage.armNextBoundaryFailure();
});
