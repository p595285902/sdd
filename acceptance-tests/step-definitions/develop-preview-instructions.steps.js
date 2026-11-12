const { Given, When, Then } = require('@cucumber/cucumber');
const { nativePage } = require('../support/pages/native-preview-page.js');
const runtime = { timeout: 420_000 };

// These non-Compose source requirements remain effective.
Given('a Development Chat checkout has a root README documenting dependency setup and non-Compose website and API startup commands with distinct localhost ports', runtime, async function () { await nativePage(this).prepareLocal(); });
Given('a Development Chat has documented non-Compose website and API commands that require local dependencies', runtime, async function () { await nativePage(this).prepareLocal(); });
Given('a Development Chat has documented startup commands that do not become ready before the configured timeout', runtime, async function () { await nativePage(this).prepareLocal('timeout'); });
When('startup instructions are resolved and executed for that chat', runtime, async function () { await nativePage(this).launchLocal(); });
When('its dependency setup and both servers run in the private workload', runtime, async function () { await nativePage(this).launchLocal(); });
When('those commands run in its private workload', runtime, async function () { await nativePage(this).launchLocal(); });
Then('the documented dependencies are installed and both documented services respond on their selected localhost ports inside that chat\'s workload', runtime, async function () { nativePage(this).expectLocalServices(); });
Then('no additional command approval is required', runtime, async function () { await nativePage(this).expectReady(); });
Then('the website can reach its API on localhost inside that workload', runtime, async function () { nativePage(this).expectLocalServices(); });
Then('neither service has a published host port or access to backend secrets', runtime, async function () { nativePage(this).expectLocalSandbox(); });
Then('startup fails with a redacted diagnostic visible in that chat', runtime, async function () { await nativePage(this).expectLocalTimeout(); });
Then('its startup processes are stopped without affecting another chat\'s workload', runtime, async function () { await nativePage(this).expectLocalTimeout(); });

Given('a Development Chat README links to checkout-local development documentation containing Compose initialization and startup instructions', runtime, async function () { await nativePage(this).prepareNative('linked'); });
When('the startup instructions are resolved for that chat', runtime, async function () { await nativePage(this).resolveInstructions(); });
Then('the ordered Compose commands are resolved with references to that documentation', runtime, async function () { nativePage(this).expectResolvedWorkflow(); });
Then('alternative host-local frontend and backend commands are not combined into the Compose workflow', runtime, async function () { nativePage(this).expectNoHostAlternative(); });
Then('no command is executed during instruction discovery', runtime, async function () { await nativePage(this).expectDiscoveryOnly(); });
Given('a Development Chat README links to an external document or a symlink outside its checkout', runtime, async function () { await nativePage(this).prepareNative('escape'); });
When('startup instructions are resolved', runtime, async function () { await nativePage(this).resolveInstructions(); });
Then('the outside document is not read automatically', runtime, async function () { nativePage(this).expectOutsideIgnored(); });
Then('an incomplete workflow produces an actionable diagnostic in that chat', runtime, async function () { await nativePage(this).expectDiagnostic(); });
Then('no undocumented command is executed', runtime, async function () { await nativePage(this).expectNoCommands(); });

Given('a documented Compose workflow requires a checkout-local environment file with database and first-user settings', runtime, async function () { await nativePage(this).prepareNative('environment'); });
When('the user launches that workflow', runtime, async function () { await nativePage(this).launchApi(); });
Then('the sandbox uses the documented project configuration', runtime, async function () { await nativePage(this).expectEnvironment(); });
Then('no platform environment values or Docker credentials are inherited', runtime, async function () { nativePage(this).expectPrivateEnvironment(); });
Then('known project secret values are masked before output is streamed or persisted', runtime, async function () { await nativePage(this).expectProjectSecretMasked(); });
Given('a Development Chat checkout has no startup commands in its README or linked checkout-local docs', runtime, async function () { await nativePage(this).prepareMissing(); });
When('the user launches the preview', runtime, async function () { await nativePage(this).launchApi(); });
Then('the user is asked in chat for a command or a checkout-local pointer', runtime, async function () { await nativePage(this).expectDiagnostic(); });
When('the user provides startup instructions', runtime, async function () { await nativePage(this).saveClarification(); });
Then('those instructions are saved only for that chat\'s preview', runtime, async function () { await nativePage(this).expectClarificationScoped(); });
Then('the project remains stopped until the user launches it again', runtime, async function () { await nativePage(this).expectSavedStopped(); });
Given('a Development Chat README documents Compose initialization followed by Compose watch', runtime, async function () { await nativePage(this).prepareNative(); });
Then('the native Compose workflow is executed in that chat\'s sandbox', runtime, async function () { await nativePage(this).expectNativeWorkflow(); });
Then('the user is not asked to provide non-Compose commands', runtime, async function () { await nativePage(this).expectNoAlternativePrompt(); });
Given('a Development Chat\'s documentation contains conflicting full-stack Docker startup instructions with no documented selection', runtime, async function () { await nativePage(this).prepareNative('conflicting'); });
Then('the conflict and its source documents are identified in that chat', runtime, async function () { await nativePage(this).expectConflict(); });
Then('no startup workflow is guessed or executed', runtime, async function () { await nativePage(this).expectNoCommands(); });
