'use strict';

const { Given, When, Then } = require('@cucumber/cucumber');

// Used by the isolated command fixture's lifecycle-failure case.
Then('those invocations use distinct project-scoped stacks', function () {
  this.lifecyclePage.distinctProjects();
});

// Isolated command-fixture lifecycle bindings never load the normal hooks.
Given('the default acceptance suite starts a fresh project-scoped stack', async function () {
  await this.lifecyclePage.legacyFreshRun();
});
When('its scenarios finish', async function () {
  await this.lifecyclePage.legacyScenariosFinish();
});
Then("only that run's project is torn down", async function () {
  await this.lifecyclePage.legacyOnlyOwnedRemoved();
});
Then('a subsequent full-suite run starts a separate fresh project', async function () {
  await this.lifecyclePage.legacyNextFreshRun();
});
