const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { runBackendPython } = require('../../features/support/app-lifecycle.js');

const startScript = `
import sys
import uuid
from app.core.config import settings
from app.services.develop_preview_runtime import PreviewController

controller = PreviewController(root=settings.DEVELOP_WORKSPACE_ROOT, url="http://preview-controller:8090")
chat_id = uuid.UUID(sys.argv[1])
try:
  started = controller.start(chat_id)
except Exception as error:
  if getattr(error, "response", None) is not None:
    print(error.response.text, file=sys.stderr)
  raise
assert started["state"] == "running"
assert controller.status(chat_id) == started
`;

class PreviewWorkloadPage {
  constructor(world) {
    this.world = world;
    this.chatIds = [];
  }

  docker(...args) {
    return execFileSync('docker', args, { encoding: 'utf8' }).trim();
  }

  containerIds(chatId) {
    const project = this.world.applicationState.projectName;
    const output = this.docker('ps', '--filter', `label=sdd.preview.chat-id=${chatId}`,
      '--filter', `label=sdd.preview.project=${project}`,
      '--filter', `name=^/${project}-preview-${chatId}$`, '--format', '{{.ID}}');
    return output ? output.split('\n') : [];
  }

  advancePastIdle() {
    const project = this.world.applicationState.projectName;
    this.docker('exec', `${project}-preview-controller-1`, 'python', '-c',
      'import sys, time; sys.path.insert(0, "/controller"); from preview_controller import sweep; sweep(now=time.time() + 301)');
  }

  isRunning(chatId) {
    return this.containerIds(chatId).length === 1;
  }

  async prepareInstructions(chatId, kind) {
    const readmes = {
      website: 'Run npm install in site, then npm run start in site on port 8765. Run python -m http.server 8766 in api on port 8766.',
      compose: 'Start the website and API with docker compose up.',
      missing: 'Project overview without startup commands.',
      timeout: 'Run npm install in site, npm run start in site on port 8765 and python -m http.server 8766 in api on port 8766.',
    };
    await this.world.apiClient.editWorkspaceFile(chatId, 'README.md', readmes[kind]);
    if (kind === 'compose' || kind === 'missing') return;
    await this.world.apiClient.editWorkspaceFile(chatId, 'site/package.json', JSON.stringify({
      scripts: { start: 'node server.js' }, dependencies: { 'is-number': '7.0.0' },
    }));
    const source = kind === 'timeout'
      ? 'setInterval(() => {}, 1000)'
      : `const http = require('node:http'); const isNumber = require('is-number');
http.createServer((request, response) => {
  http.get('http://127.0.0.1:8766/', (api) => {
    api.resume(); api.on('end', () => response.end('API reachable ' + isNumber(42)));
  }).on('error', () => { response.statusCode = 502; response.end('API unavailable'); });
}).listen(8765, '127.0.0.1');`;
    await this.world.apiClient.editWorkspaceFile(chatId, 'site/server.js', source);
    await this.world.apiClient.editWorkspaceFile(chatId, 'api/index.html', 'API response');
  }

  async selectInstructions(plan) {
    await this.world.apiClient.configureFakeLlm([{ kind: 'text', text: JSON.stringify(plan) }]);
  }

  documentedPlan() {
    return {
      setup: [{ cwd: 'site', argv: ['npm', 'install', '--ignore-scripts'] }],
      website: { cwd: 'site', argv: ['npm', 'run', 'start'], port: 8765, path: '/' },
      api: { cwd: 'api', argv: ['python', '-m', 'http.server', '8766'], port: 8766, path: '/' },
    };
  }

  async launch(chatId, answer) {
    this.chatIds.push(chatId);
    const response = await this.world.apiClient.request(this.world.apiClient.superuserToken, 'post',
      `/api/v1/develop/chats/${chatId}/preview/launch`, { data: { answer: answer || null } });
    this.lastLaunch = { status: response.status(), body: await response.json() };
    return this.lastLaunch;
  }

  async openContext(chatId) {
    this.chatIds.push(chatId);
    const response = await this.world.apiClient.request(this.world.apiClient.superuserToken, 'post',
      `/api/v1/develop/chats/${chatId}/preview/start`);
    return { status: response.status(), body: await response.json() };
  }

  async contextStatus(chatId, token = this.world.apiClient.superuserToken) {
    const response = await this.world.apiClient.request(token, 'get',
      `/api/v1/develop/chats/${chatId}/preview/status`);
    return { status: response.status(), body: await response.json() };
  }

  async completedTurn(chatId, filename) {
    const plan = this.documentedPlan();
    await this.selectInstructions(plan);
    await this.world.apiClient.configureFakeLlm([
      { kind: 'delay', delay_seconds: 3, text: 'Turn finished' },
      { kind: 'text', text: JSON.stringify(plan) },
    ]);
    const turn = this.world.apiClient.request(this.world.apiClient.superuserToken, 'post',
      `/api/v1/develop/chats/${chatId}/messages/explore/stream`, { data: { content: 'Edit checkout' } });
    await this.world.apiClient.waitForAgentTurn(this.world.apiClient.superuserToken, chatId);
    await this.world.apiClient.editWorkspaceFile(chatId, filename, `updated ${Date.now()}`);
    const result = await turn;
    assert.equal(result.status(), 200, await result.text());
  }

  serviceResponse(chatId, port) {
    return this.docker('exec', this.containerIds(chatId)[0], 'python', '-c',
      'import urllib.request; print(urllib.request.build_opener(urllib.request.ProxyHandler({})).open("http://127.0.0.1:' + port + '/").read().decode())');
  }

  async waitForServiceResponse(chatId, port, expected) {
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      if (this.serviceResponse(chatId, port).includes(expected)) return;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    assert.fail(`Preview service did not serve updated source: ${expected}`);
  }

  installedDependency(chatId) {
    return this.docker('exec', this.containerIds(chatId)[0], 'test', '-f', '/workspace/site/node_modules/is-number/package.json') === '';
  }

  expectPreviewTools(chatId) {
    const containerId = this.containerIds(chatId)[0];
    for (const tool of ['sh', 'python', 'uv', 'node', 'npm', 'bun']) {
      assert.ok(this.docker('exec', containerId, 'which', tool).length > 0, `${tool} is unavailable`);
    }
  }

  expectNoExternalNetwork(chatId) {
    const containerId = this.containerIds(chatId)[0];
    for (const address of ['http://127.0.0.1:8090/', 'http://192.168.1.1/', 'https://example.com/']) {
      assert.throws(() => this.docker('exec', containerId, 'python', '-c',
        'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)', address));
    }
  }

  async start(chatId) {
    this.chatIds.push(chatId);
    try {
      await runBackendPython(startScript, chatId);
    } catch (error) {
      execFileSync('docker', ['logs', `${this.world.applicationState.projectName}-preview-controller-1`],
        { stdio: ['ignore', 'inherit', 'inherit'] });
      throw error;
    }
    const ids = this.containerIds(chatId);
    assert.equal(ids.length, 1);
    return JSON.parse(this.docker('inspect', ids[0]))[0];
  }

  canRead(container, filename) {
    return this.docker('exec', container.Id, 'test', '-f', `/workspace/${filename}`) === '';
  }

  cannotRead(container, filename) {
    assert.throws(() => this.docker('exec', container.Id, 'test', '-e', `/workspace/${filename}`));
    assert.throws(() => this.docker('exec', container.Id, 'test', '-e', `/workspace/../${filename}`));
  }

  expectOnlyCheckout(container, chatId) {
    assert.equal(container.HostConfig.Mounts.length, 2);
    assert.equal(container.HostConfig.Mounts[0].Type, 'volume');
    assert.equal(container.HostConfig.Mounts[0].VolumeOptions.Subpath, chatId);
    assert.equal(container.Mounts.find((mount) => mount.Destination === '/checkout')?.RW, false);
    assert.ok(container.HostConfig.Tmpfs['/workspace'].includes('size=256m'));
    assert.equal(container.HostConfig.Mounts[1].Target, '/registry-socket');
    assert.equal(container.HostConfig.Mounts[1].ReadOnly, true);
  }

  expectSandbox(container) {
    const host = container.HostConfig;
    assert.equal(host.Memory, 268435456);
    assert.equal(host.NanoCpus, 1000000000);
    assert.equal(host.PidsLimit, 64);
    assert.equal(host.Privileged, false);
    assert.equal(host.ReadonlyRootfs, true);
    assert.deepEqual(host.CapDrop, ['ALL']);
    assert.ok(host.SecurityOpt.includes('no-new-privileges:true'));
    assert.equal(host.NetworkMode, 'none');
    assert.deepEqual(host.PortBindings, {});
    const environmentNames = container.Config.Env.map((entry) => entry.split('=')[0]);
    assert.deepEqual(environmentNames.sort(),
      ['HOME', 'PATH', 'PYTHON_SHA256', 'PYTHON_VERSION', 'HTTPS_PROXY', 'HTTP_PROXY',
        'NO_PROXY', 'UV_CACHE_DIR', 'npm_config_cache'].sort());
    assert.equal(container.Config.User, '65534:65534');
    assert.equal(Object.keys(container.Config.ExposedPorts || {}).length, 0);
    assert.equal((host.Binds || []).length, 0);
  }

  async stopAll() {
    for (const chatId of this.chatIds) {
      await runBackendPython(`
import sys
import uuid
from app.core.config import settings
from app.services.develop_preview_runtime import PreviewController
PreviewController(root=settings.DEVELOP_WORKSPACE_ROOT, url="http://preview-controller:8090").stop(uuid.UUID(sys.argv[1]))
`, chatId);
    }
  }
}

module.exports = { PreviewWorkloadPage };