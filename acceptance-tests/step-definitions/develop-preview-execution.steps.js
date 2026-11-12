const { Given, When, Then } = require('@cucumber/cucumber');
const { PreviewExecutionPage } = require('../support/pages/preview-execution-page.js');

const runtime = { timeout: 300_000 };
function executionPage(world) {
  world.previewExecutionPage ??= new PreviewExecutionPage(world);
  world.developContextPage ??= world.previewExecutionPage;
  return world.previewExecutionPage;
}

Given('an authenticated user has selected a Development Chat with a ready checkout and stopped preview', runtime, async function () {
  await executionPage(this).prepare();
});
Given('the selected chat has a ready checkout and resolvable Docker startup instructions', runtime, async function () {
  await executionPage(this).prepare({ mode: 'live' });
});
Given('a Development Chat\'s documented Compose workflow starts an application, a mail tool and a database administration tool', runtime, async function () {
  await executionPage(this).prepare();
});
Given('a Development Chat has a launching Compose preview', runtime, async function () {
  await executionPage(this).prepare({ mode: 'live' });
  await executionPage(this).launch();
});
Given('a Development Chat has an active preview execution with persisted output', runtime, async function () {
  await executionPage(this).prepareActive();
});
Given('a Development Chat\'s initialization command failed and its sandbox was removed', runtime, async function () {
  await executionPage(this).prepareFailed();
});
Given('an authenticated user owns a ready Development Chat with documented Compose startup', runtime, async function () {
  await executionPage(this).prepare();
});
Given('a Development Chat has no active preview execution', runtime, async function () {
  await executionPage(this).prepare();
  await executionPage(this).expectNotStarted();
});
Given('a Development Chat has persisted command output owned by another user', runtime, async function () {
  await executionPage(this).prepareOtherOwnerOutput();
});
Given('a Development Chat has an active initialization command', runtime, async function () {
  await executionPage(this).prepareActive();
});
Given('a browser disconnected after receiving part of a preview execution\'s output', runtime, async function () {
  await executionPage(this).disconnect();
});
Given('a preview execution emits output beyond its configured retention limit', runtime, async function () {
  await executionPage(this).prepareRetention();
});
Given('a documented project environment file supplies a known secret to a preview execution', runtime, async function () {
  await executionPage(this).prepare({ mode: 'secret' });
});
Given('a Development Chat\'s documentation does not identify a complete startup workflow', runtime, async function () {
  await executionPage(this).prepare({ mode: 'missing' });
});
Given('a preview command prints markup or terminal control sequences', runtime, async function () {
  await executionPage(this).prepare({ mode: 'markup' });
});

When('the user clicks Launch', runtime, async function () { await executionPage(this).launch(); });
When('the user launches its preview', runtime, async function () { await executionPage(this).launch(); });
When('the owner clicks Launch', runtime, async function () { await executionPage(this).launch(); });
When('the user opens Context through its mobile control', runtime, async function () { await executionPage(this).prepareSmallScreen(); });
When('the application becomes ready', runtime, async function () { await executionPage(this).waitUntilReady(); });
When('a command emits stdout and stderr before the application becomes ready', runtime, async function () { await executionPage(this).expectLiveOutput(); });
When('the user refreshes and reopens that chat', runtime, async function () { await executionPage(this).refresh(); });
When('the user revisits the chat', runtime, async function () { await executionPage(this).revisit(); });
When('two Launch requests for that chat arrive concurrently', runtime, async function () { await executionPage(this).concurrentLaunches(); });
When('the current user requests that execution\'s launch controls, history or stream', runtime, async function () { await executionPage(this).requestAsOtherOwner(); });
When('the command emits output while still running', runtime, async function () { await executionPage(this).expectLiveOutput(); });
When('it reconnects with the last received event cursor', runtime, async function () { await executionPage(this).receiveStreamAfterCursor(); });
When('the retained output is displayed or replayed', runtime, async function () { await executionPage(this).displayRetained(); });
When('a command prints that value across multiple stdout or stderr chunks', runtime, async function () { await executionPage(this).printSplitSecret(); });
When('its output is displayed in the chat', runtime, async function () { await executionPage(this).displayMarkup(); });

Then('Launch is available beside Expand', runtime, async function () { await executionPage(this).expectLaunchBesideExpand(); });
Then('opening Context does not execute startup commands', runtime, async function () { await executionPage(this).expectNotStarted(); });
Then('the conversation remains accessible alongside Context on desktop', runtime, async function () { await executionPage(this).expectConversationAlongside(); });
Then('that chat\'s startup begins without an approval dialog', runtime, async function () { await executionPage(this).expectNoApproval(); });
Then('Launch indicates progress without allowing another concurrent launch', runtime, async function () { await executionPage(this).expectLaunchPending(); });
Then('startup output appears in the conversation while Context remains available', runtime, async function () { await executionPage(this).expectLiveOutput(); });
Then('Launch and Expand remain accessible without horizontal page overflow', runtime, async function () { await executionPage(this).expectLaunchBesideExpand(); });
Then('launching the application does not remove access to the conversation', runtime, async function () { await executionPage(this).launchAndKeepMobileConversation(); });
Then('Context embeds the application', runtime, async function () { await executionPage(this).expectApplicationOnly(); });
Then('Context does not list or link the supporting tools', runtime, async function () { await executionPage(this).expectApplicationOnly(); });
Then('its command and both output streams appear incrementally in that chat\'s execution entry', runtime, async function () { await executionPage(this).expectLiveOutput(); });
Then('the output is not presented as an assistant reply or Agent Turn', runtime, async function () { await executionPage(this).expectNoAgentTurn(); });
Then('Context and the conversation remain usable side by side on desktop', runtime, async function () { await executionPage(this).expectConversationAlongside(); });
Then('the same execution entry and output are restored', runtime, async function () { await executionPage(this).expectRestored(); });
Then('new output attaches to that entry without duplicated events or another launch', runtime, async function () { await executionPage(this).expectMoreOutputOnce(); });
Then('the failed command, redacted diagnostic and exit status remain visible', runtime, async function () { await executionPage(this).expectFailureVisible(); });
Then('the interface does not launch a replacement preview automatically', runtime, async function () { await executionPage(this).expectNoReplacement(); });
Then('a preview execution attempt is recorded for that chat', runtime, async function () { await executionPage(this).expectRecorded(); });
Then('no assistant message or Agent Turn is created merely to run the commands', runtime, async function () { await executionPage(this).expectNoAgentTurn(); });
Then('command execution begins without a second approval request', runtime, async function () { await executionPage(this).expectNoApproval(); });
Then('exactly one execution owns the new sandbox', runtime, async function () { await executionPage(this).expectSingleOwner(); });
Then('initialization executes once', runtime, async function () { await executionPage(this).expectInitializationOnce(); });
Then('both requests identify the same active execution', function () { executionPage(this).expectSameLaunchIdentity(); });
Then('access is denied', function () { executionPage(this).expectDenied(); });
Then('no command or output from the other chat is disclosed', function () { executionPage(this).expectNoDisclosure(); });
Then('the chat receives its command-start and output events before command completion', runtime, async function () { await executionPage(this).expectLiveOutput(); });
Then('those events are already durable when displayed', runtime, async function () { await executionPage(this).expectDisplayedDurable(); });
Then('the remaining persisted events are replayed in order', runtime, async function () { await executionPage(this).expectReplayedOrder(); });
Then('new live events continue without duplicate display or another command execution', runtime, async function () { await executionPage(this).expectMoreOutputOnce(); });
Then('a truncation marker identifies omitted output', runtime, async function () { await executionPage(this).expectTruncation(); });
Then('command exit statuses and the execution\'s final status remain available', runtime, async function () { await executionPage(this).expectFinalStatusRetained(); });
Then('the secret is masked before those events are stored or delivered', runtime, async function () { await executionPage(this).expectSecretMasked(); });
Then('replay and operational logs do not reveal the original value', runtime, async function () { await executionPage(this).expectLogsMasked(); });
Then('a failed execution record explains the missing instructions in that chat', runtime, async function () { await executionPage(this).expectInstructionFailure(); });
Then('no undocumented command or sandbox application service starts', runtime, async function () { await executionPage(this).expectNothingStarted(); });
Then('the output is rendered as safe operation text', runtime, async function () { await executionPage(this).expectSafeText(); });
Then('it cannot execute scripts or become an instruction for an Agent Turn', runtime, async function () { await executionPage(this).expectNoOutputExecution(); });
