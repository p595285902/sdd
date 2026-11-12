const { Given, When, Then } = require('@cucumber/cucumber');
const { nativePage } = require('../support/pages/native-preview-page.js');
const runtime = { timeout: 420_000 };

Given('a Development Chat has a ready checkout and resolved startup instructions', runtime, async function () {
  await nativePage(this).prepareNative();
});
Given('a Development Chat has a stopped preview and resolved startup instructions', runtime, async function () {
  await nativePage(this).prepareNative();
  await nativePage(this).expectStopped();
});
When('the user opens or expands Context before any file-changing Agent Turn', runtime, async function () {
  await nativePage(this).openWithoutLaunching();
});
When('an Agent Turn completes after changing a non-ignored source file', runtime, async function () {
  await nativePage(this).completeSourceTurn();
});
Then('that chat\'s preview remains stopped', runtime, async function () { await nativePage(this).expectStopped(); });
Then('no startup command is executed', runtime, async function () { await nativePage(this).expectNoCommands(); });

Given('an authenticated user has selected a Development Chat with a ready checkout and documented Compose workflow', runtime, async function () {
  await nativePage(this).prepareNative();
  nativePage(this).otherChat = await nativePage(this).createOther();
});
When('the user clicks Launch beside Expand', runtime, async function () { await nativePage(this).launch(); });
Then('startup begins only for that chat without another approval dialog', runtime, async function () { await nativePage(this).expectOnlySelectedLaunch(); });
Then('startup commands and output appear in that chat while execution is in progress', runtime, async function () { await nativePage(this).expectLiveOutput(); });
Given('a Development Chat already has a launching or running preview', runtime, async function () { await nativePage(this).prepareDuplicate(); });
When('another Launch request arrives for that chat', runtime, async function () { await nativePage(this).launchAgain(); });
Then('no duplicate command sequence or sandbox is created', runtime, async function () { await nativePage(this).expectSameExecution(); });
Then('the existing execution status is returned', runtime, async function () { await nativePage(this).expectSameExecution(); });

Given('a Development Chat\'s preview has expired after inactivity', runtime, async function () { await nativePage(this).prepareExpired(); });
When('the user reloads the chat and opens Context', runtime, async function () { await nativePage(this).reopenExpired(); });
Then('the previous launch output remains available', runtime, async function () { await nativePage(this).expectHistoryAfterIdle(); });
Then('the preview remains stopped until another explicit Launch or Restart action', runtime, async function () { await nativePage(this).expectExplicitResume(); });

Given('the selected chat\'s documented Compose watch command is running', runtime, async function () { await nativePage(this).prepareWatch(); });
When('the main application begins responding on its resolved entry point', runtime, async function () { await nativePage(this).expectReady(); });
Then('the preview becomes ready without waiting for the watch command to exit', runtime, async function () { await nativePage(this).expectReadyWatch(); });
Then('Context displays the application rather than a supporting tool', runtime, async function () { await nativePage(this).waitUntilReady(); await nativePage(this).expectApplicationOnly(); });
Given('a Development Chat\'s database administration tool responds while its application is still starting', runtime, async function () { await nativePage(this).prepareRespondingTool(); });
When('readiness is checked', runtime, async function () { await nativePage(this).checkReadiness(); });
Then('the preview is not marked ready for that tool', runtime, async function () { await nativePage(this).expectNotReadyForTool(); });
Then('startup status continues to describe the application\'s progress', runtime, async function () { await nativePage(this).expectApplicationProgress(); });

// This source-of-truth scenario remains effective alongside the active delta.
Given('a Development Chat has an API-only checkout with documented Swagger startup', runtime, async function () { await nativePage(this).prepareSwagger(); });
When('that chat\'s preview becomes ready', runtime, async function () { await nativePage(this).launchAndWait(); });
Then('the initial preview page is its Swagger page', runtime, async function () { await nativePage(this).expectSwagger(); });
