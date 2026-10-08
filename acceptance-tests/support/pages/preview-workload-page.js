const assert = require('node:assert/strict');
const { execFileSync, spawnSync } = require('node:child_process');
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

  controllerLogs() {
    const result = spawnSync('docker', ['logs', `${this.world.applicationState.projectName}-preview-controller-1`],
      { encoding: 'utf8' });
    return `${result.stdout || ''}${result.stderr || ''}`;
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

  async prepareCompose(chatId) {
    const image = 'python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88';
    await this.world.apiClient.editWorkspaceFile(chatId, 'README.md',
      'Run `docker compose -f compose.yml up website api` to start the website and API.');
    await this.world.apiClient.editWorkspaceFile(chatId, 'compose.yml', `services:
  website:
    build:
      context: site
      dockerfile: Dockerfile
    depends_on:
      - api
    command: ["python", "server.py"]
    expose: [8765]
  api:
    build:
      context: api
      dockerfile: Dockerfile
    command: ["python", "-m", "http.server", "8766", "--bind", "0.0.0.0"]
    expose: [8766]
`);
    const dockerfile = `FROM ${image}\nCOPY . /workspace\nWORKDIR /workspace\nUSER 65534\n`;
    await this.world.apiClient.editWorkspaceFile(chatId, 'site/Dockerfile', dockerfile);
    await this.world.apiClient.editWorkspaceFile(chatId, 'api/Dockerfile', dockerfile);
    await this.world.apiClient.editWorkspaceFile(chatId, 'api/index.html', 'API reachable');
    await this.world.apiClient.editWorkspaceFile(chatId, 'site/server.py', `from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import urlopen
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        with urlopen('http://api:8766/', timeout=2) as response:
            result = response.read()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(result)
HTTPServer(('0.0.0.0', 8765), Handler).serve_forever()
`);
  }

  async prepareDependencyCompose(chatId) {
    await this.world.apiClient.editWorkspaceFile(chatId, 'README.md',
      'Run `docker compose -f compose.yml up website` to start the website.');
    await this.world.apiClient.editWorkspaceFile(chatId, 'compose.yml', `services:
  website:
    build:
      context: site
      dockerfile: Dockerfile
    command: ["python", "server.py"]
    expose: [8765]
`);
    await this.world.apiClient.editWorkspaceFile(chatId, 'site/requirements.txt', 'six==1.17.0\n');
    await this.world.apiClient.editWorkspaceFile(chatId, 'site/Dockerfile',
      'FROM python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88\nCOPY . /workspace\nWORKDIR /workspace\nRUN pip install --no-cache-dir -r requirements.txt\nUSER 65534\n');
    await this.world.apiClient.editWorkspaceFile(chatId, 'site/server.py', `from http.server import BaseHTTPRequestHandler, HTTPServer
import six
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'dependency ready' if six.PY3 else b'dependency missing')
HTTPServer(('0.0.0.0', 8765), Handler).serve_forever()
`);
  }

  async prepareNpmDependencyCompose(chatId) {
    await this.world.apiClient.editWorkspaceFile(chatId, 'site/package.json',
      JSON.stringify({ name: 'preview-site', version: '1.0.0', dependencies: { 'is-number': '7.0.0' } }));
    await this.world.apiClient.editWorkspaceFile(chatId, 'site/package-lock.json', JSON.stringify({
      name: 'preview-site', version: '1.0.0', lockfileVersion: 3, requires: true,
      packages: {
        '': { name: 'preview-site', version: '1.0.0', dependencies: { 'is-number': '7.0.0' } },
        'node_modules/is-number': {
          version: '7.0.0',
          resolved: 'https://registry.npmjs.org/is-number/-/is-number-7.0.0.tgz',
          integrity: 'sha512-41Cifkg6e8TylSpdtTpeLVMqvSBEVzTttHvERD741+pnZ8ANv0004MRL43QKPDlK9cGvNp6NZWZUBlbGXYxxng==',
        },
      },
    }));
    await this.world.apiClient.editWorkspaceFile(chatId, 'site/Dockerfile',
      'FROM node:24.15-bookworm-slim@sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d\nCOPY . /workspace\nWORKDIR /workspace\nRUN npm ci --ignore-scripts\nUSER 65534\n');
    await this.world.apiClient.editWorkspaceFile(chatId, 'compose.yml', `services:
  website:
    build:
      context: site
      dockerfile: Dockerfile
    command: ["node", "server.js"]
    expose: [8765]
`);
    await this.world.apiClient.editWorkspaceFile(chatId, 'site/server.js', `const http = require('node:http');
const isNumber = require('is-number');
http.createServer((request, response) => response.end(isNumber(42) ? 'dependency ready' : 'dependency missing')).listen(8765, '0.0.0.0');
`);
  }

  async prepareComposeDependencies(chatId) {
    const dockerfile = 'FROM python:3.14-slim-bookworm@sha256:c8137f4c460908c8763f281c8f22c431eb5c538514ba9553fc3a89c06b7cfb88\nCOPY . /workspace\nWORKDIR /workspace\nRUN pip install --no-cache-dir -r requirements.txt\nUSER 65534\n';
    for (const directory of ['site', 'api']) {
      await this.world.apiClient.editWorkspaceFile(chatId, `${directory}/requirements.txt`, 'six==1.17.0\n');
      await this.world.apiClient.editWorkspaceFile(chatId, `${directory}/Dockerfile`, dockerfile);
    }
  }

  async introduceUnsafeBuildSymlink(chatId) {
    await runBackendPython(`
import sys
import uuid
from pathlib import Path
from app.core.config import settings
from app.services.develop_workspace import workspace_path
checkout = workspace_path(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=uuid.UUID(sys.argv[1]))
(checkout / "site" / "redirect").symlink_to(Path("/etc/passwd"))
`, chatId);
  }

  async removeUnsafeBuildSymlink(chatId) {
    await runBackendPython(`
import sys
import uuid
from app.core.config import settings
from app.services.develop_workspace import workspace_path
checkout = workspace_path(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=uuid.UUID(sys.argv[1]))
target = checkout / "site" / "redirect"
assert target.is_symlink()
target.unlink()
`, chatId);
  }

  composeContainers(chatId) {
    const project = this.world.applicationState.projectName;
    const output = this.docker('ps', '--filter', `label=sdd.preview.chat-id=${chatId}`,
      '--filter', `label=sdd.preview.project=${project}`,
      '--filter', 'label=sdd.preview.compose-service', '--format', '{{.ID}}');
    return output ? output.split('\n') : [];
  }

  composeNetwork(chatId) {
    return `${this.world.applicationState.projectName}-preview-${chatId}-compose`;
  }

  composeNetworkDetails(chatId) {
    return JSON.parse(this.docker('network', 'inspect', this.composeNetwork(chatId)))[0];
  }

  assertComposeIsolation(chatId, otherChatId) {
    const network = this.composeNetworkDetails(chatId);
    assert.equal(network.Internal, true);
    assert.equal(network.Options['com.docker.network.bridge.gateway_mode_ipv4'], 'isolated');
    assert.equal(network.IPAM.Config.some((item) => item.Gateway), false);
    const backend = JSON.parse(this.docker('inspect', `${this.world.applicationState.projectName}-backend-1`))[0];
    const backendIp = backend.NetworkSettings.Networks[`${this.world.applicationState.projectName}_default`].IPAddress;
    const other = JSON.parse(this.docker('inspect', this.containerIds(otherChatId)[0]))[0];
    const otherIp = other.NetworkSettings.Networks[this.composeNetwork(otherChatId)].IPAddress;
    for (const containerId of this.composeContainers(chatId)) {
      const container = JSON.parse(this.docker('inspect', containerId))[0];
      const host = container.HostConfig;
      assert.equal(host.NetworkMode, this.composeNetwork(chatId));
      assert.equal(container.Config.User, '65534:65534');
      assert.equal(host.Memory, 268435456);
      assert.equal(host.NanoCpus, 1000000000);
      assert.equal(host.PidsLimit, 64);
      assert.equal(host.ReadonlyRootfs, true);
      assert.deepEqual(host.CapDrop, ['ALL']);
      assert.deepEqual(host.PortBindings, {});
      assert.deepEqual(host.Mounts || [], []);
      assert.deepEqual(container.Config.Env.map((entry) => entry.split('=')[0]).sort(),
        ['HOME', 'PATH', 'PYTHON_VERSION', 'PYTHON_SHA256'].sort());
      assert.ok(host.Tmpfs['/tmp'].includes('size=64m'));
      for (const address of [backendIp, otherIp, backend.NetworkSettings.Networks[`${this.world.applicationState.projectName}_default`].Gateway, '1.1.1.1']) {
        assert.throws(() => this.docker('exec', containerId, 'python', '-c',
          'import socket,sys; socket.create_connection((sys.argv[1],8000),timeout=1)', address));
      }
      assert.throws(() => this.docker('exec', containerId, 'python', '-c',
        'import socket; socket.create_connection(("host.docker.internal",8000),timeout=1)'));
    }
  }

  composeImages(chatId) {
    const project = this.world.applicationState.projectName;
    const output = this.docker('image', 'ls', '--filter', `label=sdd.preview.chat-id=${chatId}`,
      '--filter', `label=sdd.preview.project=${project}`, '--format', '{{.ID}}');
    return output ? output.split('\n') : [];
  }

  async launch(chatId, answer) {
    this.chatIds.push(chatId);
    const response = await this.world.apiClient.request(this.world.apiClient.superuserToken, 'post',
      `/api/v1/develop/chats/${chatId}/preview/launch`, { data: { answer: answer || null } });
    this.lastLaunch = { status: response.status(), body: await response.json() };
    return this.lastLaunch;
  }

  async deleteChat(chatId) {
    const response = await this.world.apiClient.request(this.world.apiClient.superuserToken, 'delete',
      `/api/v1/develop/chats/${chatId}?confirm=true`);
    assert.equal(response.status(), 200, await response.text());
  }

  async restartCompose(chatId, expectedStatus = 200, timeout = 30000) {
    const response = await this.world.apiClient.request(this.world.apiClient.superuserToken, 'post',
      `/api/v1/develop/chats/${chatId}/preview/restart`, { timeout });
    assert.equal(response.status(), expectedStatus, `${await response.text()}\n${this.controllerLogs()}`);
    if (expectedStatus === 200) assert.equal((await response.json()).state, 'running');
  }

  expireCompose(chatId) {
    this.docker('exec', `${this.world.applicationState.projectName}-preview-controller-1`, 'python', '-c',
      'import sys,time,uuid; sys.path.insert(0,"/controller"); from preview_controller import activity,activity_lock,sweep; chat=uuid.UUID(sys.argv[1]); activity_lock.acquire(); activity[chat]=time.time()-301; activity_lock.release(); sweep()', chatId);
  }

  async openContext(chatId, timeout = 30000) {
    this.chatIds.push(chatId);
    const response = await this.world.apiClient.request(this.world.apiClient.superuserToken, 'post',
      `/api/v1/develop/chats/${chatId}/preview/start`, { timeout });
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

  nodeServiceResponse(chatId, port) {
    return this.docker('exec', this.containerIds(chatId)[0], 'node', '-e',
      `require('http').get('http://127.0.0.1:${port}/',response=>{response.on('data',chunk=>process.stdout.write(chunk));response.on('end',()=>process.exit())})`);
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

  async expectRejectedCompose(chatId) {
    await runBackendPython(`
import sys
import uuid
import httpx
from app.core.config import settings
from app.services.develop_preview_runtime import PreviewController
controller = PreviewController(root=settings.DEVELOP_WORKSPACE_ROOT, url="http://preview-controller:8090")
try:
    controller.start(uuid.UUID(sys.argv[1]))
except httpx.HTTPStatusError as error:
    assert error.response.status_code == 400
else:
    raise AssertionError("Unsafe Compose was not rejected by the trusted controller")
`, chatId);
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
      try {
        await runBackendPython(`
import sys
import uuid
from app.core.config import settings
from app.services.develop_preview_runtime import PreviewController
PreviewController(root=settings.DEVELOP_WORKSPACE_ROOT, url="http://preview-controller:8090").stop(uuid.UUID(sys.argv[1]))
`, chatId);
      } catch (error) {
        console.error(this.docker('logs', `${this.world.applicationState.projectName}-preview-controller-1`));
        throw error;
      }
    }
  }
}

module.exports = { PreviewWorkloadPage };