const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { expect } = require('@playwright/test');
const { NativePreviewPage } = require('./native-preview-page.js');
const { nativeComposeFixture, ACCOUNT } = require('../native-compose-fixture.cjs');

class NativeRoutingPage extends NativePreviewPage {
  async prepareApplication({ instrumentMail = false } = {}) {
    await this.prepareNative();
    if (instrumentMail) {
      const files = nativeComposeFixture();
      await this.writeFiles({
        'compose.yml': files['compose.yml'].replace(
          "command: [python, -m, http.server, '8025']",
          "command: [python, -u, /mail.py]\n    volumes: ['./mail.py:/mail.py:ro']"),
        'mail.py': `from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  with Path('/tmp/mail-requests').open('a') as log: log.write(self.path + '\\n')
  self.send_response(200)
  self.end_headers()
  self.wfile.write(b'private mail tool')
HTTPServer(('0.0.0.0', 8025), Handler).serve_forever()
`,
      });
    }
    await this.launchApi();
    await this.expectReady();
    this.browser = await this.workload.browserContext(this.chat.id, 8765);
    if (instrumentMail) {
      this.mailContainer = this.workload.composeDetails(this.chat.id).find(container =>
        container.Config.Labels['com.docker.compose.service'] === 'mail').Id;
      await expect.poll(() => {
        try {
          return this.workload.nativeDocker(this.chat.id, 'exec', this.mailContainer, 'python', '-c',
            "import urllib.request; print(urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8025/baseline').read().decode())");
        } catch { return ''; }
      }, { timeout: 30_000 }).toContain('private mail tool');
    }
  }

  async openApplication() { this.home = await this.browser.get('/'); }

  async expectApplicationApi() {
    assert.equal(this.home.status(), 200, await this.home.text());
    assert.ok((await this.home.text()).includes('Native preview application'));
    const origin = this.workload.serviceOrigin(this.chat.id, 8765);
    const login = await this.browser.post('/api/login', { data: ACCOUNT, headers: { Origin: origin } });
    assert.equal(login.status(), 200, await login.text());
    const token = (await login.json()).token;
    assert.ok(token);
    const name = `Gateway item ${randomUUID()}`;
    const saved = await this.browser.post('/api/items', {
      data: { name }, headers: { Origin: origin, Authorization: `Bearer ${token}` },
    });
    assert.equal(saved.status(), 201, await saved.text());
    const items = await this.browser.get('/api/items', { headers: { Authorization: `Bearer ${token}` } });
    assert.equal(items.status(), 200, await items.text());
    assert.ok((await items.text()).includes(name));
  }

  async expectApplicationRoutesOnly() {
    const status = (await this.workload.contextStatus(this.chat.id)).body;
    assert.equal(status.website_port, '8765');
    assert.equal(status.api_port, '8766');
    const registeredPorts = new Set([
      status.initial_port, status.website_port, status.api_port,
      ...Object.keys(status.routes || {}), ...Object.keys(status.details?.routes || {}),
    ].filter(Boolean).map(String));
    assert.deepEqual([...registeredPorts].sort(), ['8765', '8766'], 'Only the main application and required API ports may be registered');
    await this.open();
    await this.expectApplicationOnly();
  }

  async requestPrivateTool() {
    this.probe = `forbidden-mail-${randomUUID()}`;
    const owner = await this.workload.browserContext(this.chat.id);
    this.privateResponse = await owner.get(this.workload.browserRoute(this.chat.id, 8025, this.probe));
  }

  async expectPrivateRejected() {
    assert.equal(this.privateResponse.status(), 404, await this.privateResponse.text());
    const requests = this.workload.nativeDocker(this.chat.id, 'exec', this.mailContainer,
      'python', '-c', "from pathlib import Path; print(Path('/tmp/mail-requests').read_text())");
    assert.ok(requests.includes('/baseline'), 'The mail tool must record actual requests');
    assert.ok(!requests.includes(this.probe), 'The gateway must reject the port before contacting the mail tool');
  }

  async expectApplicationAvailable() {
    const response = await this.browser.get('/');
    assert.equal(response.status(), 200, await response.text());
    assert.ok((await response.text()).includes('Native preview application'));
  }

  async prepareEqualPorts() {
    await this.prepareTwo();
    const html = nativeComposeFixture()['site/index.html'];
    this.markers = ['First sandbox application', 'Second sandbox application'];
    await this.writeFiles({ 'site/index.html': html.replace('Native preview application', this.markers[0]) });
    await this.world.apiClient.editWorkspaceFile(this.otherChat.id, 'site/index.html',
      html.replace('Native preview application', this.markers[1]));
    await this.launchApi();
    await this.expectReady();
    assert.equal((await this.workload.launch(this.otherChat.id)).status, 200);
    await this.workload.waitForPreview(this.otherChat.id);
  }

  async openEqualPorts() {
    this.responses = [];
    for (const chat of [this.chat, this.otherChat]) {
      const browser = await this.workload.browserContext(chat.id, 8765);
      this.responses.push(await browser.get('/'));
    }
  }

  async expectSeparateApplications() {
    for (let index = 0; index < this.responses.length; index += 1) {
      assert.equal(this.responses[index].status(), 200, await this.responses[index].text());
      const text = await this.responses[index].text();
      assert.ok(text.includes(this.markers[index]));
      assert.ok(!text.includes(this.markers[1 - index]));
    }
    this.expectPrivateDaemons();
  }
}

module.exports = { NativeRoutingPage };
