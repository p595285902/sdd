'use strict';

const { Given, When, Then } = require('@cucumber/cucumber');

Given('dedicated acceptance lifecycle validation runs separately from the normal scenario suite', async function () {
  await this.lifecyclePage.independentValidation();
});
When('it completes two fresh acceptance lifecycle invocations serially', async function () {
  await this.lifecyclePage.twoSerialInvocations();
});
Then('those invocations use distinct project-scoped stacks', function () {
  this.lifecyclePage.distinctProjects();
});
Then('each completed invocation leaves no owned containers, networks, or volumes', async function () {
  await this.lifecyclePage.ownedResourcesRemoved();
});
Then('neither invocation modifies unrelated project resources', async function () {
  await this.lifecyclePage.unrelatedUnchanged();
});

Given('dedicated lifecycle validation has started an isolated acceptance invocation', async function () {
  await this.lifecyclePage.startExecutionInvocation();
});
Given('unrelated project resources exist', async function () {
  await this.lifecyclePage.createUnrelatedSentinel();
});
When('that acceptance invocation fails during execution', async function () {
  await this.lifecyclePage.failInvocation();
});
Then('the failed invocation removes its owned stack and preview resources', async function () {
  await this.lifecyclePage.failedCleanup();
});
Then('unrelated project resources remain unchanged', async function () {
  await this.lifecyclePage.unrelatedUnchanged();
});
When('that invocation receives a supported cancellation signal', async function () {
  await this.lifecyclePage.cancelInvocation();
});
Then('it reports cancellation and removes its owned stack and preview resources', async function () {
  await this.lifecyclePage.cancelledCleanup();
});
Then('it does not start a replacement stack', function () {
  this.lifecyclePage.noReplacement();
});

Given('separate lifecycle validation has started the application without acceptance reset mode', async function () {
  await this.lifecyclePage.startIsolated('outside');
});
When('a client requests acceptance reset or configuration controls', async function () {
  await this.lifecyclePage.requestOutsideControls();
});
Then('those controls are unavailable', function () {
  this.lifecyclePage.controlsUnavailable();
});
Then('application data and resources remain unchanged', async function () {
  this.lifecyclePage.outsideStateUnchanged();
  await this.lifecyclePage.unrelatedUnchanged();
});

Given('separate lifecycle validation runs an isolated acceptance invocation with work that cannot quiesce within its reset deadline', async function () {
  await this.lifecyclePage.startIsolated('deadline');
});
When('that invocation requests scenario reset', async function () {
  await this.lifecyclePage.requestTerminalReset();
});
Then('reset reports failure and no later scenario starts', function () {
  this.lifecyclePage.deadlineFailed();
});
Then('the invocation fails without restarting or replacing its stack services', function () {
  this.lifecyclePage.noReplacement();
});
Then('final teardown removes its owned resources without changing unrelated projects', async function () {
  await this.lifecyclePage.failedCleanup();
});

Given('separate lifecycle validation runs an isolated acceptance invocation whose workspace or preview cleanup cannot complete', async function () {
  await this.lifecyclePage.startIsolated('cleanup');
});
Then('the failed cleanup phase is reported without a successful baseline acknowledgement', function () {
  this.lifecyclePage.cleanupFailed();
});
Then('the invocation fails and tears down rather than continuing on contaminated state', async function () {
  await this.lifecyclePage.failedCleanup();
});

// Source-of-truth-only lifecycle bindings. These never load the normal hooks.
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
