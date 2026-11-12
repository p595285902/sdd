const { Given, When, Then } = require('@cucumber/cucumber');
const { NativeRoutingPage } = require('../support/pages/native-routing-page.js');

function routing(world) {
  world.nativeRoutingPage ||= new NativeRoutingPage(world);
  return world.nativeRoutingPage;
}

Given("a Development Chat's native Compose workflow publishes application, mail tool and database administration ports inside its sandbox", { timeout: 300_000 }, async function () {
  await routing(this).prepareApplication();
});
When("the owner opens the application's registered preview address", async function () {
  await routing(this).openApplication();
});
Then('the application and its required API requests work through the private gateway', async function () {
  await routing(this).expectApplicationApi();
});
Then('the supporting-tool ports are not registered or listed in Context', async function () {
  await routing(this).expectApplicationRoutesOnly();
});

Given('a Development Chat has a ready application and a private mail tool in its sandbox', { timeout: 300_000 }, async function () {
  await routing(this).prepareApplication({ instrumentMail: true });
});
When("the owner requests the mail tool's localhost port through the preview gateway", async function () {
  await routing(this).requestPrivateTool();
});
Then('the request is rejected without contacting the mail tool', async function () {
  await routing(this).expectPrivateRejected();
});
Then("the application's registered route remains available", async function () {
  await routing(this).expectApplicationAvailable();
});

Given('two Development Chats run applications using the same sandbox-local published port', { timeout: 600_000 }, async function () {
  await routing(this).prepareEqualPorts();
});
When('their owners open their respective registered preview addresses', async function () {
  await routing(this).openEqualPorts();
});
Then("each address reaches only its owning chat's application", async function () {
  await routing(this).expectSeparateApplications();
});
Then('neither sandbox port is exposed directly on the platform host', function () {
  routing(this).expectNoPlatformPorts();
});
