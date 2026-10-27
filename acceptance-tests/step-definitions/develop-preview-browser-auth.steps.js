const assert = require('node:assert/strict');
const { createHash, createHmac, randomUUID } = require('node:crypto');
const { Given, When, Then } = require('@cucumber/cucumber');
const { configureDemoRepository } = require('../features/support/app-lifecycle.js');

Given('an authenticated user owns a Development Chat with a ready preview', async function () {
  await configureDemoRepository(true);
  await this.apiClient.authenticateSuperuser();
  this.browserChat = await this.apiClient.createDevelopmentChat(this.apiClient.superuserToken, `Browser ${randomUUID()}`);
  assert.equal((await this.apiClient.setupDevelopmentWorkspace(this.apiClient.superuserToken, this.browserChat.id)).status(), 200);
  await this.previewWorkloadPage.prepareCompose(this.browserChat.id);
  assert.equal((await this.previewWorkloadPage.openContext(this.browserChat.id)).body.state, 'ready');
});

When('the user requests browser access for that chat', async function () {
  this.browserAccess = await this.apiClient.request(this.apiClient.superuserToken, 'post',
    `/api/v1/develop/chats/${this.browserChat.id}/preview/browser-session`);
});

Then('access is bound to that chat and expires after a short period', async function () {
  assert.equal(this.browserAccess.status(), 200, await this.browserAccess.text());
  const access = await this.browserAccess.json();
  assert.equal(access.chat_id, this.browserChat.id);
  assert.ok(access.expires_in > 0 && access.expires_in <= 300);
  assert.ok(new URL(access.origin).host !== new URL(this.applicationState.baseUrl).host);
  this.browserCredential = access.credential;
  const preview = await this.openApiContext({ Host: new URL(access.origin).host });
  const response = await preview.post('/api/v1/develop/chats/preview-browser/session',
    { form: { credential: access.credential }, maxRedirects: 0 });
  assert.equal(response.status(), 303, await response.text());
  assert.equal(response.headers().location, `/api/v1/develop/chats/preview-browser/${this.browserChat.id}/`);
  this.browserCookie = response.headers()['set-cookie'];
  assert.ok(this.browserCookie?.includes('HttpOnly'));
  assert.ok(!response.headers().location.includes(this.apiClient.superuserToken));
  assert.ok(!response.headers().location.includes(access.credential));
});

Then('the preview page receives no application bearer token', async function () {
  const preview = await this.openApiContext({
    Host: new URL(this.applicationState.env.PREVIEW_ORIGIN).host,
    Cookie: this.browserCookie.split(';')[0],
  });
  const response = await preview.get(`/api/v1/develop/chats/preview-browser/${this.browserChat.id}/`);
  assert.equal(response.status(), 200, await response.text());
  assert.ok(!response.url().includes(this.apiClient.superuserToken));
  assert.ok(!(await response.text()).includes(this.apiClient.superuserToken));
  const asset = await preview.get(`/api/v1/develop/chats/preview-browser/${this.browserChat.id}/index.html`);
  assert.equal(asset.status(), 200, await asset.text());
  assert.ok(!(await asset.text()).includes(this.apiClient.superuserToken));
});

Given('a Development Chat has a browser preview session', async function () {
  await configureDemoRepository(true);
  await this.apiClient.authenticateSuperuser();
  this.browserChat = await this.apiClient.createDevelopmentChat(this.apiClient.superuserToken, `Browser ${randomUUID()}`);
  assert.equal((await this.apiClient.setupDevelopmentWorkspace(this.apiClient.superuserToken, this.browserChat.id)).status(), 200);
  await this.previewWorkloadPage.prepareCompose(this.browserChat.id);
  assert.equal((await this.previewWorkloadPage.openContext(this.browserChat.id)).body.state, 'ready');
  const response = await this.apiClient.request(this.apiClient.superuserToken, 'post',
    `/api/v1/develop/chats/${this.browserChat.id}/preview/browser-session`);
  assert.equal(response.status(), 200, await response.text());
  this.browserCredential = (await response.json()).credential;
  const preview = await this.openApiContext({ Host: new URL(this.applicationState.env.PREVIEW_ORIGIN).host });
  const exchange = await preview.post('/api/v1/develop/chats/preview-browser/session',
    { data: { credential: this.browserCredential } });
  assert.equal(exchange.status(), 200, await exchange.text());
  this.browserCookie = exchange.headers()['set-cookie'].split(';')[0];
});

When('a different user or a deleted chat requests its preview', async function () {
  const stranger = await this.apiClient.createUser();
  const token = await this.apiClient.authenticate(stranger.email, stranger.password);
  this.strangerAccess = await this.apiClient.request(token, 'post',
    `/api/v1/develop/chats/${this.browserChat.id}/preview/browser-session`);
  const host = new URL(this.applicationState.env.PREVIEW_ORIGIN).host;
  const path = `/api/v1/develop/chats/preview-browser/${this.browserChat.id}/`;
  const anonymous = await this.openApiContext({ Host: host });
  this.anonymousAccess = await anonymous.get(path);
  const key = createHash('sha256').update(`${this.applicationState.env.SECRET_KEY}:preview-browser`).digest();
  const [header, payload] = this.browserCredential.split('.');
  const expiredClaims = { ...JSON.parse(Buffer.from(payload, 'base64url').toString()), exp: 1 };
  const expiredPayload = Buffer.from(JSON.stringify(expiredClaims)).toString('base64url');
  const signature = createHmac('sha256', key).update(`${header}.${expiredPayload}`).digest('base64url');
  const expired = await this.openApiContext({ Host: host, Cookie: `preview_session=${header}.${expiredPayload}.${signature}` });
  this.expiredAccess = await expired.get(path);
  const wrongChat = await this.openApiContext({ Host: host, Cookie: this.browserCookie });
  this.wrongChatAccess = await wrongChat.get(`/api/v1/develop/chats/preview-browser/${randomUUID()}/`);
  const ownerPreview = await wrongChat.get(path);
  assert.equal(ownerPreview.status(), 200, await ownerPreview.text());
  assert.match(await ownerPreview.text(), /API reachable/);
  const deletion = await this.apiClient.deleteDevelopmentChat(this.apiClient.superuserToken, this.browserChat.id);
  assert.equal(deletion.status(), 200, await deletion.text());
  const preview = await this.openApiContext({
    Host: host, Cookie: this.browserCookie,
  });
  this.deletedAccess = await preview.get(path);
});

Then('access is denied without disclosing preview content', async function () {
  assert.equal(this.strangerAccess.status(), 404);
  assert.equal(this.anonymousAccess.status(), 404);
  assert.equal(this.expiredAccess.status(), 404);
  assert.equal(this.wrongChatAccess.status(), 404);
  assert.equal(this.deletedAccess.status(), 404);
  assert.ok(!(await this.deletedAccess.text()).includes('API reachable'));
});

Given('an authenticated user owns a Development Chat with registered website and API ports', async function () {
  await configureDemoRepository(true);
  await this.apiClient.authenticateSuperuser();
  this.browserChat = await this.apiClient.createDevelopmentChat(this.apiClient.superuserToken, `Route ${randomUUID()}`);
  assert.equal((await this.apiClient.setupDevelopmentWorkspace(this.apiClient.superuserToken, this.browserChat.id)).status(), 200);
  await this.previewWorkloadPage.prepareRoutingCompose(this.browserChat.id, 'first');
  assert.equal((await this.previewWorkloadPage.openContext(this.browserChat.id)).body.state, 'ready',
    this.previewWorkloadPage.controllerLogs());
  this.routedBrowser = await this.previewWorkloadPage.browserContext(this.browserChat.id, 8765);
});

When('the user requests its website localhost address', async function () {
  this.routedWebsite = await this.routedBrowser.get('/');
});

Then("the website and its assets load only from that chat's service", async function () {
  assert.equal(this.routedWebsite.status(), 200, await this.routedWebsite.text());
  assert.match(await this.routedWebsite.text(), /Website first/);
  const assetUrl = await this.previewWorkloadPage.assetFromPage(this.routedWebsite,
    this.previewWorkloadPage.serviceOrigin(this.browserChat.id, 8765));
  assert.equal(assetUrl.origin, this.previewWorkloadPage.serviceOrigin(this.browserChat.id, 8765));
  assert.equal(assetUrl.pathname, '/assets/site.css');
  const asset = await this.routedBrowser.get(assetUrl.pathname);
  assert.equal(asset.status(), 200, await asset.text());
  assert.match(await asset.text(), /color: green/);
  const formUrl = await this.previewWorkloadPage.formFromPage(this.routedWebsite,
    this.previewWorkloadPage.serviceOrigin(this.browserChat.id, 8765));
  assert.equal(formUrl.pathname, '/submit');
  const cookies = (await this.routedWebsite.headersArray()).filter((header) => header.name.toLowerCase() === 'set-cookie');
  assert.equal(cookies.length, 2);
  assert.ok(cookies.every((header) => !/;\s*Domain=/i.test(header.value)));
  assert.ok(cookies.every((header) => !header.value.startsWith('preview_session=')));
  const appCookies = cookies.map((header) => header.value.split(';')[0]).join('; ');
  const appBrowser = await this.openApiContext({
    Host: new URL(formUrl).host,
    Cookie: `${this.previewWorkloadPage.browserCookie}; ${appCookies.split('; ')[0]}; app_session=root; `
      + `preview_session_${randomUUID()}=other-chat; ${appCookies.split('; ')[1]}`,
  });
  const form = await this.previewWorkloadPage.submitServiceForm(appBrowser, formUrl);
  assert.equal(form.status(), 200, `${await form.text()}\n${this.previewWorkloadPage.controllerLogs()}`);
  assert.match(await form.text(), /Form alice title=saved/);
  const logout = await this.routedBrowser.get('/logout');
  const logoutHeaders = await logout.headersArray();
  assert.ok(logoutHeaders.some((header) =>
    header.name.toLowerCase() === 'set-cookie' && /^app_session=(?:"")?;.*Max-Age=-1/i.test(header.value)),
  `Logout returned ${logout.status()} with headers ${JSON.stringify(logoutHeaders)}`);
  const foreignForm = await this.previewWorkloadPage.submitServiceForm(this.routedBrowser, formUrl, 'https://example.com');
  assert.equal(foreignForm.status(), 403, await foreignForm.text());
  const missingOriginForm = await this.previewWorkloadPage.submitServiceForm(this.routedBrowser, formUrl, null);
  assert.equal(missingOriginForm.status(), 403, await missingOriginForm.text());
  const redirect = await this.routedBrowser.get('/return', { maxRedirects: 0 });
  assert.equal(redirect.status(), 302, await redirect.text());
  assert.equal(redirect.headers().location, `${this.previewWorkloadPage.serviceOrigin(this.browserChat.id, 8765)}/result`);
  const relative = await this.routedBrowser.get('/docs/relative', { maxRedirects: 0 });
  assert.equal(relative.status(), 302, await relative.text());
  assert.equal(relative.headers().location,
    `${this.previewWorkloadPage.serviceOrigin(this.browserChat.id, 8765)}/docs/assets/app.js?mode=preview`);
  const relativeAsset = await this.routedBrowser.get('/docs/assets/app.js?mode=preview');
  assert.equal(relativeAsset.status(), 200, await relativeAsset.text());
  assert.match(await relativeAsset.text(), /relativeAsset/);
  const apiRedirect = await this.routedBrowser.get('/api-return', { maxRedirects: 0 });
  assert.equal(apiRedirect.status(), 302, await apiRedirect.text());
  assert.equal(apiRedirect.headers().location, `${this.previewWorkloadPage.serviceOrigin(this.browserChat.id, 8766)}/docs`);
  const apiHost = new URL(apiRedirect.headers().location).host;
  const redirected = await this.openApiContext({ Host: apiHost, Cookie: this.previewWorkloadPage.browserCookie });
  const redirectedSwagger = await redirected.get('/docs/');
  assert.equal(redirectedSwagger.status(), 200, await redirectedSwagger.text());
  assert.match(await redirectedSwagger.text(), /Swagger first/);
  const reload = await this.previewWorkloadPage.browserHotReload(this.browserChat.id).catch((error) => {
    throw new Error(`${error.message}\n${this.previewWorkloadPage.controllerLogs()}`);
  });
  assert.match(reload, /101 Switching Protocols/);
  assert.match(reload, /Sec-WebSocket-Protocol: vite-hmr/i);
  assert.match(reload, /reload/);
  const foreign = await this.previewWorkloadPage.browserHotReload(this.browserChat.id, 'https://example.com');
  assert.match(foreign, /403 Forbidden/);
  assert.doesNotMatch(foreign, /reload/);
  const otherService = await this.previewWorkloadPage.browserHotReload(this.browserChat.id,
    this.previewWorkloadPage.serviceOrigin(this.browserChat.id, 8766));
  assert.match(otherService, /403 Forbidden/);
  assert.doesNotMatch(otherService, /reload/);
});

When('the user requests its API localhost Swagger address', async function () {
  this.routedApiBrowser = await this.previewWorkloadPage.browserContext(this.browserChat.id, 8766);
  this.routedSwagger = await this.routedApiBrowser.get('/docs/');
});

Then("that chat's Swagger page loads", async function () {
  assert.equal(this.routedSwagger.status(), 200, await this.routedSwagger.text());
  assert.match(this.routedSwagger.headers()['content-type'], /text\/html/);
  assert.match(await this.routedSwagger.text(), /Swagger first/);
  const specUrl = await this.previewWorkloadPage.assetFromPage(this.routedSwagger,
    this.previewWorkloadPage.serviceOrigin(this.browserChat.id, 8766), 'a');
  assert.equal(specUrl.pathname, '/openapi.json');
  const spec = await this.routedApiBrowser.get(specUrl.pathname);
  assert.equal(spec.status(), 200, await spec.text());
  assert.equal((await spec.json()).info.title, 'first');
  const scriptUrl = await this.previewWorkloadPage.assetFromPage(this.routedSwagger,
    this.previewWorkloadPage.serviceOrigin(this.browserChat.id, 8766), 'script');
  const script = await this.routedApiBrowser.get(scriptUrl.pathname);
  assert.equal(script.status(), 200, await script.text());
  assert.match(await script.text(), /swaggerReady/);
});

Given('a Development Chat has a registered website port', async function () {
  await configureDemoRepository(true);
  await this.apiClient.authenticateSuperuser();
  this.browserChat = await this.apiClient.createDevelopmentChat(this.apiClient.superuserToken, `Route ${randomUUID()}`);
  assert.equal((await this.apiClient.setupDevelopmentWorkspace(this.apiClient.superuserToken, this.browserChat.id)).status(), 200);
  await this.previewWorkloadPage.prepareRoutingCompose(this.browserChat.id, 'first');
  assert.equal((await this.previewWorkloadPage.openContext(this.browserChat.id)).body.state, 'ready');
  this.routedBrowser = await this.previewWorkloadPage.browserContext(this.browserChat.id);
});

When('the user requests an external URL or an unregistered localhost port', async function () {
  this.externalRoute = await this.routedBrowser.get(this.previewWorkloadPage.browserRoute(this.browserChat.id, 8765, '//example.com'));
  this.externalUrlRoute = await this.routedBrowser.get(this.previewWorkloadPage.browserRoute(this.browserChat.id, 8765, 'https://example.com'));
  this.unknownRoute = await this.routedBrowser.get(this.previewWorkloadPage.browserRoute(this.browserChat.id, 9876));
  this.externalRedirect = await this.previewWorkloadPage.browserExternalRedirect(this.routedBrowser, this.browserChat.id);
  this.schemeRelativeRedirect = await this.routedBrowser.get(
    this.previewWorkloadPage.browserRoute(this.browserChat.id, 8765, 'scheme-relative-return'), { maxRedirects: 0 });
});

Then('navigation is rejected without contacting that destination', function () {
  assert.equal(this.externalRoute.status(), 404);
  assert.equal(this.externalUrlRoute.status(), 404);
  assert.equal(this.unknownRoute.status(), 404);
  assert.equal(this.externalRedirect.status(), 404);
  assert.equal(this.schemeRelativeRedirect.status(), 404);
});

Given('two Development Chats each have a registered localhost port', async function () {
  await configureDemoRepository(true);
  await this.apiClient.authenticateSuperuser();
  this.browserChat = await this.apiClient.createDevelopmentChat(this.apiClient.superuserToken, `Route ${randomUUID()}`);
  this.otherBrowserChat = await this.apiClient.createDevelopmentChat(this.apiClient.superuserToken, `Route ${randomUUID()}`);
  for (const [chat, content] of [[this.browserChat, 'first'], [this.otherBrowserChat, 'second']]) {
    assert.equal((await this.apiClient.setupDevelopmentWorkspace(this.apiClient.superuserToken, chat.id)).status(), 200);
    await this.previewWorkloadPage.prepareRoutingCompose(chat.id, content);
    assert.equal((await this.previewWorkloadPage.openContext(chat.id)).body.state, 'ready');
  }
  this.routedBrowser = await this.previewWorkloadPage.browserContext(this.browserChat.id);
});

When("a user requests the first chat's route with the second chat's service address", async function () {
  this.crossChatRoute = await this.routedBrowser.get(this.previewWorkloadPage.browserRoute(this.otherBrowserChat.id, 8765));
  const secondHost = new URL(this.previewWorkloadPage.serviceOrigin(this.otherBrowserChat.id, 8765)).host;
  const crossHost = await this.openApiContext({ Host: secondHost, Cookie: this.previewWorkloadPage.browserCookie });
  this.crossChatHost = await crossHost.get('/');
});

Then("the gateway does not return the second chat's preview content", async function () {
  assert.equal(this.crossChatRoute.status(), 404);
  assert.doesNotMatch(await this.crossChatRoute.text(), /Website second/);
  assert.equal(this.crossChatHost.status(), 404);
  assert.doesNotMatch(await this.crossChatHost.text(), /Website second/);
});