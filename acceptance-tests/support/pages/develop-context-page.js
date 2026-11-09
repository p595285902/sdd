const { expect } = require('@playwright/test');
const { mkdir } = require('node:fs/promises');
const path = require('node:path');

class DevelopContextPage {
  constructor(world) {
    this.world = world;
  }

  get page() {
    return this.world.page;
  }

  get panel() {
    return this.page.getByRole('complementary', { name: 'Development context' }).filter({ visible: true });
  }

  get frame() {
    return this.page.frameLocator('iframe[title="Development preview"]');
  }

  get address() {
    return this.panel.getByRole('textbox', { name: 'Preview address' });
  }

  async prepareCompose(chatId, label, apiOnly = false) {
    const { apiClient, previewWorkloadPage } = this.world;
    await apiClient.withWorkspaceFileBatch(chatId, async () => {
      await previewWorkloadPage.prepareCompose(chatId);
      if (apiOnly) {
        await apiClient.editWorkspaceFile(chatId, 'README.md',
          'Run `docker compose -f compose.yml up api`. API Swagger UI is at http://localhost:8766/docs/.');
        await apiClient.editWorkspaceFile(chatId, 'compose.yml', `services:
  api:
    build:
      context: api
      dockerfile: Dockerfile
    command: ["python", "-m", "http.server", "8766", "--bind", "0.0.0.0"]
    expose: [8766]
`);
      }
      await apiClient.editWorkspaceFile(chatId, 'api/docs/index.html', `<!doctype html><html><body>
<h1>Swagger UI</h1><button onclick="fetch('/openapi.json').then(r=>r.json()).then(s=>document.querySelector('output').textContent=s.info.title)">Load schema</button>
<output></output></body></html>`);
      await apiClient.editWorkspaceFile(chatId, 'api/openapi.json', JSON.stringify({
        openapi: '3.1.0', info: { title: label, version: '1.0.0' }, paths: {},
      }));
      if (!apiOnly) {
        await apiClient.editWorkspaceFile(chatId, 'site/server.py', `from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/details':
            body = b'<html><body><h1>Details ${label}</h1></body></html>'
        else:
            body = b'''<!doctype html><html><body><h1>${label}</h1>
<button onclick="document.querySelector('output').textContent = 'Items: ' + (++window.items)">Add item</button>
<output>Items: 0</output><script>window.items = 0</script>
<a href="/details">Open details</a><a href="https://example.com/context-preview">External page</a></body></html>'''
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(body)
HTTPServer(('0.0.0.0', 8765), Handler).serve_forever()
`);
      }
    });
  }

  async open() {
    const mobile = this.page.getByRole('button', { name: 'Open development context' });
    if (await mobile.isVisible()) await mobile.click();
    await expect(this.panel).toBeVisible();
  }

  get previewElement() {
    return this.panel.locator('iframe[title="Development preview"]');
  }

  async expectReadyPanel(label) {
    await this.open();
    try {
      const heading = this.frame.getByRole('heading', { name: label, exact: true });
      if (this.activityClockPaused) {
        // React Query batches network-result notifications through zero-delay timers.
        // Flush those while waiting for real requests, without advancing a heartbeat interval.
        await expect.poll(async () => {
          await this.page.clock.runFor(10);
          return heading.isVisible();
        }, { timeout: 45_000 }).toBe(true);
      } else {
        await expect(heading).toBeVisible({ timeout: 45_000 });
      }
    } catch (error) {
      const panel = await this.panel.textContent();
      const frames = this.page.frames().map(frame => ({ name: frame.name(), url: frame.url() }));
      await this.captureLayout('develop-context-ready-failure');
      throw new Error(`${error.message}\nContext: ${panel}\nFrames: ${JSON.stringify(frames)}`);
    }
    await expect(this.previewElement).toHaveCount(1);
    await this.expectToolbar();
    await expect(this.panel.getByRole('status')).toHaveCount(0);
  }

  async activateWithKeyboard(control) {
    await expect(control).toBeVisible();
    await expect(control).toBeEnabled();
    await control.focus();
    await expect(control).toBeFocused();
    await control.press('Enter');
  }

  async expectNoPageOverflow() {
    const dimensions = await this.page.evaluate(() => ({
      viewport: document.documentElement.clientWidth,
      page: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    }));
    expect(dimensions.page).toBeLessThanOrEqual(dimensions.viewport + 1);
  }

  async previewBox() {
    const box = await this.previewElement.boundingBox();
    expect(box).not.toBeNull();
    expect(box.width).toBeGreaterThan(0);
    expect(box.height).toBeGreaterThanOrEqual(320);
    return box;
  }

  async expectSameFrame(original) {
    expect(await this.previewElement.evaluate((current, previous) => current === previous, original))
      .toBe(true);
  }

  async addItem(expected) {
    await this.frame.getByRole('button', { name: 'Add item' }).click();
    await expect(this.frame.locator('output')).toHaveText(`Items: ${expected}`);
  }

  async captureLayout(name) {
    await this.expectNoPageOverflow();
    const directory = path.resolve(__dirname, '../../reports');
    await mkdir(directory, { recursive: true });
    const png = await this.page.screenshot({ path: path.join(directory, `${name}.png`), fullPage: true });
    if (typeof this.world.attach === 'function') await this.world.attach(png, 'image/png');
  }

  async expandContext() {
    await this.page.setViewportSize({ width: 1440, height: 1000 });
    await this.expectReadyPanel(this.world.previewLabel);
    this.compactDesktopBox = await this.previewBox();
    this.compactDesktopFrame = await this.previewElement.elementHandle();
    await this.addItem(1);
    await this.activateWithKeyboard(this.panel.getByRole('button', { name: 'Expand Context', exact: true }));
    await expect(this.panel.getByRole('button', { name: 'Collapse Context', exact: true })).toBeVisible();
  }

  async expectStableNavigation(label) {
    const before = await this.previewBox();
    const frame = await this.previewElement.elementHandle();
    const destination = new URL('/details', (await frame.contentFrame()).url()).href;
    let release;
    const held = new Promise(resolve => { release = resolve; });
    const handled = [];
    const intercept = route => {
      const continuation = held.then(() => route.continue());
      handled.push(continuation);
      return continuation;
    };
    await this.page.route(destination, intercept);
    try {
      const loading = this.page.waitForRequest(request =>
        request.url() === destination && request.isNavigationRequest());
      await this.navigate(8765, '/details');
      await loading;
      await expect(this.panel.getByRole('status')).toContainText('Loading preview');
      const during = await this.previewBox();
      for (const dimension of ['x', 'y', 'width', 'height']) {
        expect(Math.abs(during[dimension] - before[dimension])).toBeLessThanOrEqual(1);
      }
      await this.expectNoPageOverflow();
    } finally {
      release();
      await Promise.all(handled);
      await this.page.unroute(destination, intercept);
    }
    await this.expectDetails(label);
    await expect(this.panel.getByRole('status')).toHaveCount(0);
    const after = await this.previewBox();
    for (const dimension of ['x', 'y', 'width', 'height']) {
      expect(Math.abs(after[dimension] - before[dimension])).toBeLessThanOrEqual(1);
    }
    await this.navigate(8765, '/');
    await this.expectReadyPanel(label);
  }

  async expectDesktopConversationControls() {
    await expect(this.page.getByRole('navigation', { name: 'Development Chats' })).toBeVisible();
    await expect(this.page.getByRole('region', { name: 'Conversation', exact: true })).toBeVisible();
    for (const control of [
      this.page.getByRole('textbox', { name: 'Exploration message', exact: true }),
      this.page.getByRole('button', { name: 'Rename Development Chat', exact: true }),
      this.page.getByRole('combobox', { name: 'Presence Mode' }),
      this.page.getByRole('button', { name: 'Delete Development Chat', exact: true }),
    ]) {
      await expect(control).toBeInViewport();
      await expect(control).toBeEnabled();
    }
    const draft = this.page.getByRole('textbox', { name: 'Exploration message', exact: true });
    await draft.fill('Unsent preview layout check');
    await expect(this.page.getByRole('button', { name: 'Send exploration', exact: true })).toBeEnabled();
    await draft.fill('');
  }

  async expectWiderInteractiveViewports(label) {
    await expect.poll(async () => (await this.previewBox()).width)
      .toBeGreaterThan(this.compactDesktopBox.width + 32);
    await this.expectSameFrame(this.compactDesktopFrame);
    await expect(this.frame.locator('output')).toHaveText('Items: 1');
    await this.addItem(2);
    await this.expectDesktopConversationControls();
    await this.expectStableNavigation(label);
    await this.addItem(1);
    await this.captureLayout('develop-context-desktop-expanded');
    const desktopFrame = await this.previewElement.elementHandle();
    await this.activateWithKeyboard(this.panel.getByRole('button', { name: 'Collapse Context', exact: true }));
    await expect.poll(async () => (await this.previewBox()).width)
      .toBeLessThanOrEqual(this.compactDesktopBox.width + 1);
    await this.expectSameFrame(desktopFrame);
    await expect(this.frame.locator('output')).toHaveText('Items: 1');
    await this.addItem(2);
    await this.captureLayout('develop-context-desktop-collapsed');

    await this.page.setViewportSize({ width: 390, height: 844 });
    await this.expectReadyPanel(label);
    const compactMobile = await this.previewBox();
    const mobileFrame = await this.previewElement.elementHandle();
    const priorItems = await this.frame.locator('output').textContent();
    await this.activateWithKeyboard(this.panel.getByRole('button', { name: 'Expand Context', exact: true }));
    await expect(this.panel.getByRole('button', { name: 'Collapse Context', exact: true })).toBeVisible();
    await expect.poll(async () => (await this.previewBox()).width).toBeGreaterThan(compactMobile.width + 16);
    await this.expectSameFrame(mobileFrame);
    await expect(this.frame.locator('output')).toHaveText(priorItems);
    const expanded = await this.panel.boundingBox();
    const content = await this.page.getByRole('region', { name: 'Conversation', exact: true }).boundingBox();
    expect(expanded).not.toBeNull();
    expect(content).not.toBeNull();
    // Either inline order is valid; the preview must not cover the conversation.
    expect(expanded.y + expanded.height <= content.y + 1 ||
      content.y + content.height <= expanded.y + 1).toBe(true);
    const viewport = this.page.viewportSize();
    expect(expanded.x).toBeGreaterThanOrEqual(0);
    expect(expanded.x + expanded.width).toBeLessThanOrEqual(viewport.width + 1);
    expect(expanded.width).toBeGreaterThanOrEqual(content.width - 1);
    await this.expectStableNavigation(label);
    await this.addItem(1);
    await this.captureLayout('develop-context-mobile-expanded');
    const expandedFrame = await this.previewElement.elementHandle();
    await this.activateWithKeyboard(this.panel.getByRole('button', { name: 'Collapse Context', exact: true }));
    await expect.poll(async () => (await this.previewBox()).width).toBeLessThanOrEqual(compactMobile.width + 1);
    await this.expectSameFrame(expandedFrame);
    await expect(this.frame.locator('output')).toHaveText('Items: 1');
    await this.addItem(2);
    await this.captureLayout('develop-context-mobile-collapsed');
    await this.activateWithKeyboard(this.panel.getByRole('button', { name: 'Expand Context', exact: true }));
  }

  async expectConversationControlsAccessible() {
    const back = this.panel.getByRole('button', { name: 'Close panel', exact: true });
    await expect(back).toHaveAttribute('title', 'Back to chat');
    await this.activateWithKeyboard(back);
    await expect(this.panel).toHaveCount(0);
    for (const control of [
      this.page.getByRole('button', { name: 'Rename Development Chat', exact: true }),
      this.page.getByRole('combobox', { name: 'Presence Mode' }),
      this.page.getByRole('button', { name: 'Delete Development Chat', exact: true }),
    ]) {
      await control.scrollIntoViewIfNeeded();
      await expect(control).toBeInViewport();
      await expect(control).toBeEnabled();
      await control.focus();
      await expect(control).toBeFocused();
    }
    const draft = this.page.getByRole('textbox', { name: 'Exploration message', exact: true });
    await draft.scrollIntoViewIfNeeded();
    await expect(draft).toBeInViewport();
    await draft.fill('Unsent mobile preview check');
    const send = this.page.getByRole('button', { name: 'Send exploration', exact: true });
    await expect(send).toBeEnabled();
    await expect(send).toBeInViewport();
    await draft.fill('');
    await this.expectNoPageOverflow();
    await this.page.setViewportSize({ width: 1440, height: 1000 });
    await this.open();
    await this.expectDesktopConversationControls();
    await this.expectNoPageOverflow();
  }

  async observeActivity(chatId) {
    this.activityChatId = chatId;
    this.activityRequests = [];
    this.activityOtherChat = await this.world.apiClient.createDevelopmentChat(
      this.world.userToken, `${this.world.previewLabel} alternate chat`,
    );
    this.activityListener = request => {
      if (request.method() === 'POST' &&
          new URL(request.url()).pathname === `/api/v1/develop/chats/${chatId}/preview/activity`) {
        this.activityRequests.push(request);
      }
    };
    this.page.on('request', this.activityListener);
    // Install before navigating to the application, so all heartbeat timers use this clock.
    await this.page.clock.install();
  }

  async expectSuccessfulActivity() {
    for (const request of this.activityRequests) {
      const response = await request.response();
      expect(response, 'Actual activity request must receive a response').not.toBeNull();
      expect(response.ok(), await response.text()).toBe(true);
    }
  }

  async expectVisibleHeartbeat() {
    await expect.poll(() => this.activityRequests.length).toBeGreaterThan(0);
    await this.page.clock.pauseAt(await this.page.evaluate(() => Date.now() + 100));
    this.activityClockPaused = true;
    await this.expectSuccessfulActivity();
    const before = this.activityRequests.length;
    await this.page.clock.runFor(30_000);
    await expect.poll(() => this.activityRequests.length).toBe(before + 1);
    await this.expectSuccessfulActivity();
  }

  async expectQuietHeartbeat() {
    const before = this.activityRequests.length;
    await this.page.clock.runFor(60_000);
    await this.page.evaluate(() => Promise.resolve());
    expect(this.activityRequests.length, 'Hidden or deselected Context must not send activity').toBe(before);
  }

  async expectActivityResumed(action) {
    const before = this.activityRequests.length;
    await action();
    await expect.poll(() => this.activityRequests.length).toBe(before + 1);
    await this.expectSuccessfulActivity();
    await this.page.clock.runFor(30_000);
    await expect.poll(() => this.activityRequests.length).toBe(before + 2);
    await this.expectSuccessfulActivity();
  }

  async hideContextAndSwitchTabs() {
    await this.activateWithKeyboard(this.panel.getByRole('button', { name: 'Hide Context', exact: true }));
    await expect(this.panel).toHaveCount(0);
    await this.expectQuietHeartbeat();
    await this.expectActivityResumed(async () => {
      await this.open();
      await this.expectReadyPanel(this.world.previewLabel);
    });
    this.otherTab = await this.world.context.newPage();
    await this.otherTab.goto('about:blank');
    await this.otherTab.bringToFront();
    if (await this.page.evaluate(() => document.visibilityState) !== 'hidden') {
      // Automated Chromium keeps tabs visible. Exercise the actual visibility API integration
      // with a scoped signal, not a mocked activity endpoint or a claim of native tab coverage.
      this.visibilityOverride = await this.page.evaluateHandle(() => {
        const descriptor = Object.getOwnPropertyDescriptor(document, 'visibilityState');
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
        document.dispatchEvent(new Event('visibilitychange'));
        return { descriptor };
      });
      if (typeof this.world.attach === 'function') {
        await this.world.attach('Tab visibility uses a scoped document.visibilityState/visibilitychange signal; native Chromium tab switching remains a manual check.', 'text/plain');
      }
    }
    await expect.poll(() => this.page.evaluate(() => document.visibilityState)).toBe('hidden');
  }

  async restoreTabVisibility() {
    await this.page.bringToFront();
    if (this.visibilityOverride) {
      await this.page.evaluate(({ descriptor }) => {
        if (descriptor) Object.defineProperty(document, 'visibilityState', descriptor);
        else delete document.visibilityState;
        document.dispatchEvent(new Event('visibilitychange'));
      }, this.visibilityOverride);
      await this.visibilityOverride.dispose();
      this.visibilityOverride = null;
    }
    await this.otherTab?.close();
    this.otherTab = null;
    await expect.poll(() => this.page.evaluate(() => document.visibilityState)).toBe('visible');
  }

  async expectActivityStoppedForChat() {
    try {
      await this.expectQuietHeartbeat();
      await this.expectActivityResumed(() => this.restoreTabVisibility());
      await this.world.developPage.selectChat(this.activityOtherChat.title);
      await this.expectStatus();
      await this.expectQuietHeartbeat();
      await this.expectActivityResumed(async () => {
        await this.world.developPage.selectChat(this.world.developmentChat.title);
        await this.expectReadyPanel(this.world.previewLabel);
      });
    } finally {
      await this.restoreTabVisibility();
      this.page.off('request', this.activityListener);
      await this.page.clock.resume();
      this.activityClockPaused = false;
    }
  }

  async expectStatus() {
    await expect(this.panel).toContainText(/set\s*up|instructions|stopped|failed|unavailable|error|Compose/i);
    await expect(this.panel.locator('iframe[title="Development preview"]')).toHaveCount(0);
  }

  async expectWebsite(label) {
    try {
      await expect(this.frame.getByRole('heading', { name: label, exact: true })).toBeVisible({ timeout: 45_000 });
    } catch (error) {
      const panel = await this.panel.textContent();
      const frames = this.page.frames().map(frame => ({ name: frame.name(), url: frame.url() }));
      throw new Error(`${error.message}\nContext: ${panel}\nFrames: ${JSON.stringify(frames)}`);
    }
    await this.frame.getByRole('button', { name: 'Add item' }).click();
    await expect(this.frame.locator('output')).toHaveText('Items: 1');
  }

  async expectLocalAddress(port = 8765, path = '/') {
    await expect(this.address).toHaveValue(`http://localhost:${port}${path}`);
  }

  async expectToolbar() {
    await expect(this.address).toBeVisible();
    await expect(this.panel.getByRole('button', { name: 'Reload preview' })).toBeEnabled();
    await expect(this.panel.getByRole('button', { name: 'Restart preview' })).toBeEnabled();
    await expect(this.panel.getByRole('button', { name: /^(Back|Forward)$/ })).toHaveCount(0);
  }

  async navigate(port, path) {
    await this.address.fill(`http://localhost:${port}${path}`);
    await this.address.press('Enter');
  }

  async expectDetails(label) {
    await expect(this.frame.getByRole('heading', { name: `Details ${label}`, exact: true })).toBeVisible();
  }

  async expectSwagger(label) {
    await expect(this.frame.getByRole('heading', { name: 'Swagger UI' })).toBeVisible({ timeout: 90_000 });
    await this.frame.getByRole('button', { name: 'Load schema' }).click();
    await expect(this.frame.locator('output')).toHaveText(label);
  }

  async expectReloadAndExternalNavigation(label) {
    await this.navigate(8765, '/');
    await expect(this.frame.getByRole('heading', { name: label, exact: true })).toBeVisible();
    await this.frame.getByRole('button', { name: 'Add item' }).click();
    await expect(this.frame.locator('output')).toHaveText('Items: 1');
    await this.panel.getByRole('button', { name: 'Reload preview' }).click();
    await expect(this.frame.locator('output')).toHaveText('Items: 0');
    await this.page.route('https://example.com/context-preview', route => route.fulfill({
      contentType: 'text/html', body: '<h1>External destination</h1>',
    }));
    await this.frame.getByRole('link', { name: 'External page' }).click();
    await expect(this.frame.getByRole('heading', { name: 'External destination' })).toBeVisible();
    await expect.poll(async () => {
      const frame = await this.panel.locator('iframe[title="Development preview"]').elementHandle();
      return (await frame.contentFrame()).url();
    }).toBe('https://example.com/context-preview');
  }

  async restartWithHeldRequest() {
    await this.page.route('**/api/v1/develop/chats/*/preview/restart', async route => {
      await new Promise(resolve => { this.releaseRestart = resolve; });
      await route.continue();
    });
    await this.panel.getByRole('button', { name: 'Restart preview' }).click();
  }

  async expectStartupThenRelease() {
    await expect(this.panel).toContainText(/starting|restarting|startup|loading/i);
    await expect(this.panel.locator('iframe[title="Development preview"]')).toHaveCount(0);
    await expect.poll(() => typeof this.releaseRestart).toBe('function');
    this.releaseRestart();
  }

  async expectNoOtherChat(label) {
    await expect(this.panel).not.toContainText(label);
    await expect(this.panel.locator('iframe[title="Development preview"]')).toHaveCount(0);
  }
}

module.exports = { DevelopContextPage };
