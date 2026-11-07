const { expect } = require('@playwright/test');

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
