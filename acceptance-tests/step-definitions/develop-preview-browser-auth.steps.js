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