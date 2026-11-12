const { Given, When, Then } = require('@cucumber/cucumber');
const { nativePage } = require('../support/pages/native-preview-page.js');
const runtime = { timeout: 420_000 };

Given('two Development Chats have separate checkouts of the same repository', runtime, async function () { await nativePage(this).prepareTwo(); });
When('a preview workload starts for each chat', runtime, async function () { await nativePage(this).launchBoth(); });
Then('each workload uses only its own chat\'s checkout', runtime, async function () { nativePage(this).expectOwnCheckouts(); });
Then('neither workload is mounted with the other chat\'s checkout', runtime, async function () { nativePage(this).expectOwnCheckouts(); });
Given('a Development Chat has a ready checkout', runtime, async function () { await nativePage(this).prepareNative(); });
When('its preview workload starts', runtime, async function () { await nativePage(this).launchApi(); await nativePage(this).expectReady(); });
Then('the workload has resource limits and no backend credentials', runtime, async function () { nativePage(this).expectPrivateEnvironment(); });
Then('it has no host control socket or publicly published service port', runtime, async function () { nativePage(this).expectPrivateEnvironment(); nativePage(this).expectNoPlatformPorts(); });

// Effective source scenarios: idle lifetime, visible activity and owner deletion.
Given('a Development Chat has a running preview workload', runtime, async function () {
  await nativePage(this).prepareNative();
  await nativePage(this).launchApi();
  await nativePage(this).expectReady();
  await nativePage(this).page.goto('about:blank');
});
When('five minutes pass without visible Context activity', runtime, async function () {
  if (nativePage(this).fixtureKind === 'output-idle') await nativePage(this).waitForRealIdle();
  else this.previewWorkloadPage.advancePastIdle();
});
Then('its preview workload is stopped', runtime, async function () { await nativePage(this).expectRemoved(); });
Then('its Development Chat remains available', runtime, async function () { await nativePage(this).expectChatAvailable(); });
When('the user continues to use its visible Context panel', runtime, async function () { await nativePage(this).visibleActivity(); });
Then('the preview workload remains running', runtime, async function () { await nativePage(this).expectReady(); });
Given('two Development Chats have running preview workloads', runtime, async function () { await nativePage(this).prepareTwo(); await nativePage(this).launchBoth(); });
When('the user deletes one Development Chat', runtime, async function () { await nativePage(this).deleteSelected(); });
Then('only the deleted chat\'s preview workload is removed', runtime, async function () { await nativePage(this).expectRemoved(); await nativePage(this).expectOtherRunning(); });

Given('two Development Chats document the same fixed container names and published application ports', runtime, async function () { await nativePage(this).prepareTwo(); });
When('both native Compose workflows are explicitly launched', runtime, async function () { await nativePage(this).launchBoth(); });
Then('both applications can run without name or port collisions', runtime, async function () { nativePage(this).expectBothApplications(); });
Then('neither project\'s published ports are directly exposed on the platform host', runtime, async function () { nativePage(this).expectNoPlatformPorts(); });
Given('the platform process has Docker connection settings and private environment credentials', runtime, async function () { await nativePage(this).preparePlatformEnvironment(); });
When('a Development Chat\'s native Compose command executes', runtime, async function () { await nativePage(this).launchApi(); await nativePage(this).expectReady(); });
Then('Docker connection settings select only that chat\'s private daemon', runtime, async function () { nativePage(this).expectPrivateDockerConnection(); });
Then('platform Docker configuration and credentials are absent from its execution environment', runtime, async function () { nativePage(this).expectPrivateEnvironment(); });

Given('a trusted deployment explicitly enables privileged outer preview sandboxes', runtime, async function () { await nativePage(this).preparePrivilegedDeployment(); });
When('the owner launches a documented Compose preview', runtime, async function () { await nativePage(this).launchApi(); await nativePage(this).expectReady(); });
Then('only that chat\'s outer sandbox is provisioned in privileged mode', runtime, async function () { nativePage(this).expectPrivilegedOuterOnly(); });
Then('its private Docker daemon runs as the rootless user', runtime, async function () { nativePage(this).expectRootlessDaemon(); });
Then('no platform socket, host bind mount, platform credential or other checkout is injected', runtime, async function () { nativePage(this).expectPrivateEnvironment(); });
Then('aggregate sandbox resource limits remain configured', runtime, async function () { nativePage(this).expectResourceLimits(); });
Then('no application ports are published on the platform host', runtime, async function () { nativePage(this).expectNoPlatformPorts(); });
Given('the deployment cannot provision a private Docker sandbox within its configured privilege policy', runtime, async function () { await nativePage(this).prepareUnprovisionable(); });
When('the user launches a preview', runtime, async function () { await nativePage(this).launchUnprovisionable(); });
Then('launch fails with an actionable diagnostic retained in the chat', runtime, async function () { await nativePage(this).expectProvisionFailure(); });
Then('execution does not fall back to the platform\'s shared Docker daemon', runtime, async function () { nativePage(this).expectNoFallback(); });

Given('a Development Chat has a running Compose preview and persisted launch output', runtime, async function () { await nativePage(this).prepareIdle(); });
Then('its sandbox and command sessions are stopped and removed', runtime, async function () { await nativePage(this).expectRemoved(); });
Then('its chat retains the redacted commands, output and stopped status', runtime, async function () { await nativePage(this).expectIdleHistory(); });
Given('a Development Chat has a running preview with no visible Context activity', runtime, async function () { await nativePage(this).prepareIdle(); });
When('its watch command continues emitting output for five minutes', runtime, async function () { await nativePage(this).waitForRealIdle(); });
Then('the output does not keep the preview workload alive', runtime, async function () { await nativePage(this).expectRemoved(); });
Then('the chat retains the final stopped status', runtime, async function () { await nativePage(this).expectIdleHistory(); });
Given('a persisted preview execution is active but its sandbox no longer exists after controller restart', runtime, async function () { await nativePage(this).removeAndRestartController(); });
When('execution status is reconciled', runtime, async function () { await nativePage(this).reconcile(); });
Then('the chat shows a terminal interrupted status for that execution', runtime, async function () { await nativePage(this).expectInterrupted(); });
Then('no replacement sandbox starts without an explicit user action', runtime, async function () { await nativePage(this).expectNoReplacementSandbox(); });
