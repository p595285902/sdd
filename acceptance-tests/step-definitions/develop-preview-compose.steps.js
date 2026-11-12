const { Given, When, Then } = require('@cucumber/cucumber');
const { nativePage } = require('../support/pages/native-preview-page.js');
const runtime = { timeout: 420_000 };

Given('a Development Chat checkout has a README describing an existing Compose file with website and API services', runtime, async function () { await nativePage(this).prepareNative(); });
When('that chat\'s preview starts', runtime, async function () { await nativePage(this).launchApi(); });
Then('the website and API start in that chat\'s private Compose project', runtime, async function () { await nativePage(this).expectNativeConfiguration(); });
Then('another chat with the same repository uses a different Compose project', runtime, async function () { await nativePage(this).startOther(); nativePage(this).expectPrivateDaemons(); });
Given('a Development Chat checkout has a documented Compose website that depends on an API', runtime, async function () { await nativePage(this).prepareNative(); });
When('the chat\'s private Compose project starts', runtime, async function () { await nativePage(this).launchApi(); await nativePage(this).expectReady(); });
Then('the website can reach its API by service name within that chat\'s network', runtime, async function () { nativePage(this).expectApplicationApi(); });
Then('neither service is attached to the platform or another chat\'s private network', runtime, async function () { await nativePage(this).startOther(); nativePage(this).expectPrivateDaemons(); });
Given('a Development Chat checkout has runnable README commands but no documented Compose file', runtime, async function () { await nativePage(this).preparePlainCommands(); });
Then('the documented commands run without generating a Compose file', runtime, async function () { await nativePage(this).expectPlainCommands(); });
Given('a documented Compose file requests host networking or a Docker socket mount', runtime, async function () { await nativePage(this).prepareNative('unsafe'); });
Then('the unsafe preview configuration is rejected', runtime, async function () { await nativePage(this).expectUnsafeRejected(); });
Then('requested host networking and Docker socket mounts are not provisioned', runtime, async function () { await nativePage(this).expectRemoved(); });

Given('a Development Chat README documents a one-off Compose database initialization command followed by a Compose watch command', runtime, async function () { await nativePage(this).prepareNative(); });
When('the user launches the documented workflow', runtime, async function () { await nativePage(this).launch(); });
Then('the initialization command completes successfully before the watch command starts', runtime, async function () { await nativePage(this).expectInitializationOrder(); });
Then('application readiness can be reported while the watch command remains running', runtime, async function () { await nativePage(this).expectReadyWatch(); });
Then('both commands and their output are visible in that chat', runtime, async function () { await nativePage(this).expectCommandsVisible(); });
Given('a documented Compose workflow uses default override files, a project environment file, named volumes and a health-checked database dependency', runtime, async function () { await nativePage(this).prepareNative(); });
When('the user launches the workflow without explicit service names', runtime, async function () { await nativePage(this).launchApi(); });
Then('native Compose applies those files and dependency conditions inside the owning chat\'s sandbox', runtime, async function () { await nativePage(this).expectNativeConfiguration(); });
Then('sandbox-local published ports and fixed container names do not collide with another chat or the platform', runtime, async function () { await nativePage(this).startOther(); nativePage(this).expectBothApplications(); });
Then('the checkout\'s Compose files remain unchanged', runtime, async function () { await nativePage(this).expectUnchanged(); });
Given('a documented Compose workflow has initialization followed by application startup', runtime, async function () {
  await nativePage(this).prepareNative('failed');
  await nativePage(this).startOther();
});
When('the initialization command exits with a nonzero status', runtime, async function () { await nativePage(this).launchInitializationFailure(); });
Then('the application startup command is not executed', runtime, async function () { await nativePage(this).expectNoLaterStartup(); });
Then('the failed command and exit status remain visible in that chat', runtime, async function () { await nativePage(this).expectInitializationFailure(); });
Then('partial runtime resources are cleaned up only for that chat', runtime, async function () { await nativePage(this).expectOnlyFailedResourcesGone(); });

Given('a Development Chat has a documented Compose application with a frontend, API, database and first-user initialization', runtime, async function () { await nativePage(this).prepareNative(); });
Then('the application becomes usable inside Context', runtime, async function () { await nativePage(this).expectUsableApplication(); });
When('the user logs in with the initialized preview account and creates an item', runtime, async function () { await nativePage(this).createApplicationItem(); });
Then('the item is saved through the application\'s API and database', runtime, async function () { nativePage(this).expectDatabaseItem(); });
Given('a Development Chat has a running native Compose sandbox with configured resource limits', runtime, async function () { await nativePage(this).prepareNative(); await nativePage(this).launchApi(); await nativePage(this).expectReady(); });
When('its project creates additional services or build processes', runtime, async function () { await nativePage(this).addResourceProcesses(); });
Then('those processes remain within the owning sandbox\'s aggregate resource limits', runtime, async function () { nativePage(this).expectAggregateBudget(); });
Then('no platform secrets, host bind mounts or control sockets are injected into the sandbox', runtime, async function () { nativePage(this).expectPrivateEnvironment(); });
