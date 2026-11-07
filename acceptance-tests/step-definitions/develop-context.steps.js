const { Given, When, Then } = require('@cucumber/cucumber');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { configureDemoRepository } = require('../features/support/app-lifecycle.js');
const { DevelopContextPage } = require('../support/pages/develop-context-page.js');

function contextPage(world) {
  world.developContextPage ??= new DevelopContextPage(world);
  return world.developContextPage;
}

async function prepareComposeChat(world, apiOnly = false) {
  await configureDemoRepository(true);
  world.userToken = await world.apiClient.authenticateSuperuser();
  world.previewLabel = `Compose preview ${randomUUID()}`;
  world.developmentChat = await world.apiClient.createDevelopmentChat(world.userToken, world.previewLabel);
  const setup = await world.apiClient.setupDevelopmentWorkspace(world.userToken, world.developmentChat.id);
  assert.equal(setup.status(), 200, await setup.text());
  await contextPage(world).prepareCompose(world.developmentChat.id, world.previewLabel, apiOnly);
  const started = await world.previewWorkloadPage.openContext(world.developmentChat.id, 120_000);
  assert.equal(started.body.state, 'ready', JSON.stringify(started.body));
  await world.developPage.open(world.userToken);
  await world.developPage.selectChat(world.developmentChat.title);
}

Given('an authenticated user has selected a Development Chat with a ready Compose website preview',
  { timeout: 150_000 }, async function () {
    await prepareComposeChat(this);
  });

Given('an authenticated user has selected a Development Chat with a ready Compose API preview',
  { timeout: 150_000 }, async function () {
    await prepareComposeChat(this, true);
  });

When('the user opens Context', async function () {
  await contextPage(this).open();
});

Then('the website can be used inside Context', async function () {
  await contextPage(this).expectWebsite(this.previewLabel);
});

Then('the browser shows its localhost address', async function () {
  await contextPage(this).expectLocalAddress();
});

Then('the preview toolbar offers address entry, Reload and Restart', async function () {
  await contextPage(this).expectToolbar();
});

When('the user enters a registered localhost path in the URL bar', async function () {
  await contextPage(this).navigate(8765, '/details');
});

Then("that path loads from the selected chat's preview", async function () {
  await contextPage(this).expectDetails(this.previewLabel);
  await contextPage(this).expectReloadAndExternalNavigation(this.previewLabel);
});

When('the user enters its localhost Swagger address in Context', async function () {
  await contextPage(this).open();
  await contextPage(this).expectLocalAddress(8766, '/docs/');
  await contextPage(this).navigate(8766, '/docs/');
});

Then('Swagger loads inside Context', async function () {
  await contextPage(this).expectSwagger(this.previewLabel);
});

When('the user selects Restart preview', async function () {
  await contextPage(this).open();
  await contextPage(this).expectToolbar();
  await contextPage(this).restartWithHeldRequest();
});

Then("Context shows startup progress until that chat's preview is ready", async function () {
  await contextPage(this).expectStartupThenRelease();
});

Then("the Context panel shows that chat's preview or current status", async function () {
  await contextPage(this).expectStatus();
});

Given('an authenticated user has selected a Development Chat without a ready Compose preview',
  { timeout: 150_000 }, async function () {
    await prepareComposeChat(this);
    const readyChat = this.developmentChat;
    const missingChat = await this.apiClient.createDevelopmentChat(
      this.userToken, `Missing preview ${randomUUID()}`,
    );
    await this.developPage.open(this.userToken);
    await this.developPage.selectChat(readyChat.title);
    await contextPage(this).expectWebsite(this.previewLabel);
    await this.developPage.selectChat(missingChat.title);
    this.developmentChat = missingChat;
  });

Then("Context shows that chat's setup or failure status", async function () {
  await contextPage(this).expectStatus();
});

Then("another chat's preview is not displayed", async function () {
  await contextPage(this).expectNoOtherChat(this.previewLabel);
});
