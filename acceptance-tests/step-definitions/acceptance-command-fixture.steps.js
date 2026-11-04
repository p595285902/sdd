'use strict';
const { When } = require('@cucumber/cucumber');

// Only isolated complete-command validation inventories contain this intent.
When('the isolated command fixture arms a bounded filesystem cleanup fault', async function () {
  await this.resetPage.armNextBoundaryFailure();
});
