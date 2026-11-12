const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { expect } = require('@playwright/test');
const { backendPythonOutput, configureDemoRepository } = require('../../features/support/app-lifecycle.js');
const { nativeComposeFixture, ACCOUNT } = require('../native-compose-fixture.cjs');
const { PreviewExecutionPage } = require('./preview-execution-page.js');

const WAIT = 240_000;
const IDLE_WAIT = 360_000;

class NativePreviewPage extends PreviewExecutionPage {
  get workload() { return this.world.previewWorkloadPage; }

  async prepareNative(kind = 'normal') {
    await this.prepare({ mode: kind === 'failed' ? 'failed' : kind === 'missing' ? 'missing' : 'normal' });
    this.fixtureKind = kind;
    if (kind === 'linked') {
      const files = nativeComposeFixture({ linked: true });
      await this.writeFiles({ 'README.md': files['README.md'], 'docs/development.md': files['docs/development.md'] });
    }
    if (kind === 'slow-application') {
      const files = this.workload.nativeFixtures.get(this.chat.id);
      await this.writeFiles({ 'site/server.py': 'import time\ntime.sleep(45)\n' + files['site/server.py'] });
    }
    if (kind === 'output-idle') {
      const files = this.workload.nativeFixtures.get(this.chat.id);
      await this.writeFiles({
        // Standalone `compose watch` does not attach service logs. This fixture
        // needs the real foreground watch command to stream ongoing output.
        'README.md': files['README.md'].replace('docker compose watch', 'docker compose up --watch'),
        'site/server.py': `import threading, time

def periodic_output():
    index = 0
    while True:
        print('native watch activity tick ' + str(index), flush=True)
        index += 1
        time.sleep(2)
threading.Thread(target=periodic_output, daemon=True).start()
` + files['site/server.py'] });
    }
    if (kind === 'environment') {
      const files = this.workload.nativeFixtures.get(this.chat.id);
      await this.writeFiles({ 'api/init.py': "import os\nprint('project credential ' + os.environ['FIRST_PASSWORD'], flush=True)\n" + files['api/init.py'] });
    }
    if (kind === 'conflicting') {
      const files = this.workload.nativeFixtures.get(this.chat.id);
      await this.writeFiles({
        'README.md': files['README.md'] + '\nSee [alternative Docker stack](docs/alternative.md).\n',
        'docs/alternative.md': '# Alternative full-stack Docker workflow\n```sh\ndocker compose up website api\n```\nApplication: http://localhost:8765/\n',
      });
    }
    if (kind === 'escape') {
      await this.writeFiles({ 'README.md': '# Development\nSee [external startup](https://example.invalid/never-fetch-startup.md) or [escaped startup](docs/escape.md).\n' });
      await backendPythonOutput(`
import sys, uuid
from pathlib import Path
from app.core.config import settings
from app.services.develop_workspace import workspace_path
root = workspace_path(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=uuid.UUID(sys.argv[1]))
(root / 'docs').mkdir(exist_ok=True)
(root / 'docs' / 'escape.md').symlink_to('/etc/passwd')
`, this.chat.id);
    }
    if (kind === 'unsafe') {
      await this.writeFiles({
        'README.md': 'Run `docker compose up website` for the website at http://localhost:8765/.\n',
        'compose.yml': 'services:\n  website:\n    image: python:3.14-slim-bookworm\n    command: [python, -m, http.server, "8765"]\n    network_mode: host\n    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]\n',
        // The normal fixture's override adds api/db/tool services. They have no
        // image in this replacement model and would hide the host-access check
        // behind an unrelated native Compose configuration error.
        'compose.override.yml': 'services: {}\n',
      });
    }
    this.savedFiles = await this.checkoutFiles(['compose.yml', 'compose.override.yml', '.env']);
  }

  async writeFiles(files) {
    await this.world.apiClient.withWorkspaceFileBatch(this.chat.id, async () => {
      for (const [name, content] of Object.entries(files)) await this.world.apiClient.editWorkspaceFile(this.chat.id, name, content);
    });
  }

  async checkoutFiles(names) {
    return JSON.parse(await backendPythonOutput(`
import json, sys, uuid
from app.core.config import settings
from app.services.develop_workspace import workspace_path
root = workspace_path(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=uuid.UUID(sys.argv[1]))
print(json.dumps({name: (root / name).read_text() if (root / name).is_file() else None for name in json.loads(sys.argv[2])}))
`, this.chat.id, JSON.stringify(names)));
  }

  async prepareLocal(kind = 'website') {
    await configureDemoRepository(true);
    this.world.userToken = await this.world.apiClient.authenticateSuperuser();
    this.world.developmentChat = await this.world.apiClient.createDevelopmentChat(this.token, `Local instructions ${randomUUID()}`);
    assert.equal((await this.world.apiClient.setupDevelopmentWorkspace(this.token, this.chat.id)).status(), 200);
    await this.workload.prepareInstructions(this.chat.id, kind);
    await this.workload.selectInstructions(this.workload.documentedPlan());
    this.workload.chatIds.push(this.chat.id);
    this.fixtureKind = `local-${kind}`;
    this.beforeMessages = (await this.world.apiClient.listDevelopmentMessages(this.token, this.chat.id)).data;
    await this.world.developPage.open(this.token);
    await this.world.developPage.selectChat(this.chat.title);
    if (kind === 'timeout') {
      this.otherChat = await this.createOther(false);
      await this.workload.selectInstructions(this.workload.documentedPlan());
      await this.workload.openContext(this.otherChat.id);
    }
  }

  async createOther(native = true) {
    const chat = await this.world.apiClient.createDevelopmentChat(this.token, `Other preview ${randomUUID()}`);
    assert.equal((await this.world.apiClient.setupDevelopmentWorkspace(this.token, chat.id)).status(), 200);
    if (native) await this.workload.prepareNativeCompose(chat.id);
    else await this.workload.prepareInstructions(chat.id, 'website');
    this.workload.chatIds.push(chat.id);
    return chat;
  }

  async launchApi() {
    this.launchedAt = Date.now();
    const result = await this.workload.launch(this.chat.id);
    assert.equal(result.status, 200);
    assert.ok(result.body.execution?.id);
    this.launchResult = result.body;
    this.execution = result.body.execution;
    // API-driven fixtures do not trigger the browser's Launch mutation/cache
    // invalidation. Reopen the selected chat through the real UI to restore its
    // persisted operation, without adding client-side state or another launch.
    // Idle fixtures deliberately stay on about:blank and must remain hidden.
    if (new URL(this.page.url()).pathname === '/develop') {
      await this.world.developPage.open(this.token);
      await this.world.developPage.selectChat(this.chat.title);
    }
  }

  async launchAndWait() {
    await this.launchApi();
    await this.waitForExecution(row => row.ready || ['failed', 'stopped', 'interrupted'].includes(row.status));
  }

  async expectReady() {
    await this.waitForExecution(row => row.ready && row.status === 'running', 'the documented application to respond');
    assert.equal((await this.workload.contextStatus(this.chat.id)).body.state, 'ready');
  }

  async resolveInstructions() {
    const response = await this.request('context');
    assert.equal(response.status(), 200);
    this.discoveryStatus = await response.json();
    this.discovered = JSON.parse(await backendPythonOutput(`
import json, sys, uuid
from app.core.config import settings
from app.services.develop_workspace import workspace_path
from app.services.preview_native_plan import resolve_native_plan, read_startup_documents
root = workspace_path(root=settings.DEVELOP_WORKSPACE_ROOT, chat_id=uuid.UUID(sys.argv[1]))
try:
    documents = read_startup_documents(root)
    plan = resolve_native_plan(root)
    print(json.dumps({'plan': plan.as_dict() if plan else None, 'documents': [doc.path for doc in documents]}))
except (ValueError, OSError) as error:
    print(json.dumps({'error': str(error)}))
`, this.chat.id));
    await this.open();
  }

  expectResolvedWorkflow() {
    const plan = this.discovered.plan;
    assert.equal(plan.runtime, 'native-compose');
    assert.deepEqual(plan.commands.map(command => command.argv), [
      ['docker', 'compose', 'run', '--rm', 'api', 'python', 'init.py'], ['docker', 'compose', 'watch'],
    ]);
    assert.ok(plan.commands.every(command => command.cwd === '.' && command.source.path === 'docs/development.md' && command.source.line > 0));
    assert.ok(plan.sources.some(source => source.path === 'docs/development.md' && source.sha256.length === 64));
  }

  expectNoHostAlternative() {
    assert.ok(this.discovered.plan.commands.every(command => command.argv[0] === 'docker'));
    assert.ok(!JSON.stringify(this.discovered.plan.commands).includes('site/server.py'));
  }

  async expectNoCommands() {
    assert.equal(this.workload.isRunning(this.chat.id), false);
    for (const execution of await this.executions()) {
      const response = await this.json(`executions/${execution.id}/events?after=0`);
      assert.ok(!response.data.some(event => event.kind === 'command_start'));
    }
  }

  async expectDiscoveryOnly() {
    await this.expectNoCommands();
    assert.deepEqual(await this.executions(), [], 'Instruction resolution must not record a launch');
  }

  expectOutsideIgnored() {
    assert.deepEqual(this.discovered.documents, ['README.md']);
    assert.equal(this.discovered.plan, null);
  }

  async expectDiagnostic(pattern = /instruction|command|pointer|workflow/i) {
    await this.open();
    if (this.execution) {
      await this.waitForExecution(row => row.status === 'failed');
      const events = await this.events();
      assert.match(events.filter(event => event.kind === 'status').map(event => event.payload.reason || '').join('\n'), pattern);
      await expect(this.operation).toBeVisible({ timeout: WAIT });
      await this.expandOperation();
      await expect(this.commandOutput).toContainText(pattern, { timeout: WAIT });
    } else await expect(this.panel).toContainText(pattern);
    assert.deepEqual((await this.world.apiClient.listDevelopmentMessages(this.token, this.chat.id)).data, this.beforeMessages,
      'Instruction diagnostics belong to operations, not invented assistant messages');
  }

  async saveClarification() {
    this.clarification = 'docker compose run --rm api python init.py\ndocker compose watch\nApplication: http://localhost:8765/';
    const response = await this.request('launch', 'post', this.token, { data: { answer: this.clarification } });
    assert.equal(response.status(), 200);
    const saved = await response.json();
    assert.equal(saved.state, 'stopped');
    this.execution = saved.execution;
  }

  async expectClarificationScoped() {
    const rows = await this.executions();
    assert.equal(rows[0].workflow.preview_instructions.answer, this.clarification);
    const other = await this.createOther();
    const history = await this.workload.executionHistory(other.id);
    assert.deepEqual(history, []);
    assert.ok(!(await this.world.apiClient.listDevelopmentMessages(this.token, other.id)).data.some(message => message.content.includes(this.clarification)));
  }

  async expectSavedStopped() {
    await this.expectNoCommands();
    assert.equal((await this.executions()).filter(row => ['starting', 'running'].includes(row.status)).length, 0);
    // Saving is not approval; only a subsequent, distinct Launch executes it.
    await this.launchApi();
    await this.expectReady();
  }

  async expectNativeWorkflow() {
    await this.expectReady();
    assert.ok(this.workload.isNative(this.chat.id));
    assert.ok((await this.events()).some(event => event.kind === 'command_start' && event.payload.argv?.includes('watch')));
  }

  async expectNoAlternativePrompt() {
    assert.equal(this.execution.status, 'running');
    await expect(this.operation).not.toContainText(/provide non-Compose|unsupported Compose/i);
  }

  async expectConflict() {
    await this.expectDiagnostic(/conflict/i);
    const diagnostic = (await this.events()).map(event => event.payload.reason || '').join('\n');
    assert.ok(diagnostic.includes('README.md') && diagnostic.includes('docs/alternative.md'));
  }

  async expectEnvironment() {
    await this.expectReady();
    const api = this.workload.serviceContainer(this.chat.id, 8766);
    const environment = JSON.parse(this.workload.nativeDocker(this.chat.id, 'inspect', api))[0].Config.Env;
    assert.ok(environment.includes(`FIRST_EMAIL=${ACCOUNT.email}`) && environment.includes(`FIRST_PASSWORD=${ACCOUNT.password}`));
    assert.ok(this.workload.nativeDocker(this.chat.id, 'exec', api, 'python', '-c', "from db import query; print(query('SELECT count(*) FROM users'))").includes('1'));
  }

  expectPrivateEnvironment(chatId = this.chat.id) {
    const sandbox = this.workload.inspect(chatId);
    this.workload.expectSandbox(sandbox);
    this.workload.expectOnlyCheckout(sandbox, chatId);
    const platform = JSON.parse(this.workload.docker('inspect', `${this.world.applicationState.projectName}-backend-1`))[0];
    const credentials = platform.Config.Env.filter(value => /^(?:SECRET_KEY|OPENAI_API_KEY|POSTGRES_PASSWORD|FIRST_SUPERUSER_PASSWORD|ACCEPTANCE_RESET_TOKEN)=/.test(value));
    const nested = this.workload.composeDetails(chatId);
    for (const container of [sandbox, ...nested]) {
      const environment = (container.Config.Env || []).join('\n');
      for (const entry of credentials) {
        const value = entry.slice(entry.indexOf('=') + 1);
        if (value) assert.ok(!environment.includes(value), 'Platform credential value must not be inherited');
      }
      assert.ok((container.Mounts || []).filter(mount => mount.Type === 'bind').every(mount =>
        (mount.Source === '/workspace' || mount.Source.startsWith('/workspace/')) && !/docker\.sock|containerd\.sock/.test(mount.Source)),
        'Project bind inputs must be confined to the synchronized checkout, never platform host paths or control sockets');
    }
    const config = JSON.parse(this.workload.docker('exec', sandbox.Id, 'python3', '-c',
      "from pathlib import Path; print((Path.home()/'.docker/config.json').read_text())"));
    assert.deepEqual(config.auths || {}, {});
    assert.ok(!config.credsStore && !config.credHelpers && !config.currentContext);
  }

  async expectProjectSecretMasked() {
    const events = await this.waitForEvents(rows => rows.some(event => event.payload.text?.includes('project credential')));
    assert.ok(!JSON.stringify(events).includes(ACCOUNT.password));
    assert.ok(events.some(event => event.payload.text?.includes('[REDACTED]')));
    await this.expandOperation();
    await expect(this.commandOutput).toContainText('[REDACTED]');
    assert.ok(!(await this.commandOutput.textContent()).includes(ACCOUNT.password));
  }

  async openWithoutLaunching() {
    await this.open();
    const expand = this.panel.getByRole('button', { name: 'Expand Context', exact: true });
    await expand.click();
    await expect(this.panel.getByRole('button', { name: 'Collapse Context', exact: true })).toBeVisible();
  }

  async expectStopped() {
    assert.equal((await this.workload.contextStatus(this.chat.id)).body.state, 'stopped');
    assert.equal(this.workload.isRunning(this.chat.id), false);
  }

  async completeSourceTurn() {
    await this.workload.completedTurn(this.chat.id, 'site/feature.py');
  }

  async expectOnlySelectedLaunch() {
    await this.expectNoApproval();
    assert.ok(this.workload.isRunning(this.chat.id));
    if (this.otherChat) assert.equal(this.workload.isRunning(this.otherChat.id), false);
  }

  async prepareDuplicate() {
    await this.prepareNative();
    await this.launch();
    this.firstExecution = this.execution.id;
    this.firstSandbox = this.workload.inspect(this.chat.id).Id;
  }

  async launchAgain() {
    await this.launchApi();
  }

  async expectSameExecution() {
    assert.equal(this.execution.id, this.firstExecution);
    assert.equal(this.workload.inspect(this.chat.id).Id, this.firstSandbox);
    assert.equal((await this.executions()).length, 1);
    await this.waitForEvents(events => events.some(event => event.kind === 'command_start'));
    const starts = (await this.events()).filter(event => event.kind === 'command_start');
    assert.equal(new Set(starts.map(event => event.payload.command)).size, starts.length);
  }

  async leaveReadyContext() {
    const activityPath = `/api/v1/develop/chats/${this.chat.id}/preview/activity`;
    let latestActivity;
    const observe = request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === activityPath) {
        latestActivity = { request, at: Date.now() };
      }
    };
    this.page.on('request', observe);
    try {
      const [response] = await Promise.all([
        this.page.waitForResponse(response => response.request().method() === 'POST' &&
          new URL(response.url()).pathname === activityPath, { timeout: WAIT }),
        (async () => {
          await this.world.developPage.open(this.token);
          await this.world.developPage.selectChat(this.chat.title);
          await this.open();
        })(),
      ]);
      assert.ok(response.ok(), 'Visible Context activity must reach the real controller');
      await this.page.goto('about:blank');
      const lastResponse = await latestActivity.request.response();
      assert.ok(lastResponse?.ok(), 'The final visible Context heartbeat must succeed');
      this.idleBeganAt = latestActivity.at;
    } finally {
      this.page.off('request', observe);
    }
  }

  async prepareExpired() {
    await this.prepareIdle();
    await this.waitForRealIdle();
    this.previousEvents = await this.events();
  }

  async waitForRealIdle() {
    const began = this.idleBeganAt;
    assert.ok(began, 'A real visible Context heartbeat must establish the running preview idle window');
    const initial = await this.events();
    let last = initial.at(-1)?.sequence || 0;
    const outputMinutes = new Set();
    const abort = new AbortController();
    const response = await fetch(new URL(`/api/v1/develop/chats/${this.chat.id}/preview/executions/${this.execution.id}/stream?after=${last}`,
      this.world.applicationState.baseUrl), { headers: { Authorization: `Bearer ${this.token}`, Accept: 'text/event-stream' }, signal: abort.signal });
    assert.equal(response.status, 200);
    const reader = response.body.getReader();
    let liveBytes = 0;
    let streamError;
    const consuming = (async () => {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        liveBytes += value.byteLength;
      }
    })().catch(error => { streamError = error; });
    try {
      await expect.poll(async () => {
        const rows = await this.executions();
        this.execution = rows.find(row => row.id === this.execution.id);
        const events = await this.events();
        if (events.some(event => event.sequence > last && event.payload.text?.includes('native watch activity tick'))) {
          outputMinutes.add(Math.floor((Date.now() - began) / 60_000));
        }
        last = events.at(-1)?.sequence || last;
        return this.execution.status;
      }, { timeout: IDLE_WAIT, intervals: [1000], message: 'A connected output stream and replay requests must not renew the five-minute visible-Context lifetime' }).toBe('stopped');
    } finally {
      abort.abort();
      await consuming;
      reader.releaseLock();
    }
    assert.ok(liveBytes > 0, 'An actual owner-authenticated output stream must remain attached during the idle test');
    if (streamError && streamError.name !== 'AbortError') throw streamError;
    assert.ok(Date.now() - began >= 300_000, 'Idle cleanup must use the real five-minute lifetime, not a separate-process activity map');
    for (let minute = 0; minute < 5; minute++) {
      assert.ok(outputMinutes.has(minute), `The watch command must emit actual output in idle minute ${minute + 1}; observed ${[...outputMinutes]}`);
    }
    await expect.poll(() => this.workload.isRunning(this.chat.id), { timeout: WAIT }).toBe(false);
  }

  async reopenExpired() {
    await this.world.developPage.open(this.token);
    await this.world.developPage.selectChat(this.chat.title);
    await this.open();
  }

  async expectHistoryAfterIdle() {
    await this.expandOperation();
    await expect(this.commandOutput).toContainText('init.py');
    await expect(this.operation.locator('summary')).toContainText('stopped');
    assert.equal(this.execution.id, this.previousExecution || this.execution.id);
    assert.ok((await this.events()).some(event => event.kind === 'command_start'));
    assert.ok(!JSON.stringify(await this.events()).includes(this.secret));
  }

  async expectExplicitResume() {
    await this.expectStopped();
    assert.equal((await this.executions()).length, 1);
    await this.panel.getByRole('button', { name: 'Launch preview', exact: true }).click();
    await expect.poll(async () => (await this.executions()).length, { timeout: WAIT }).toBe(2);
    const latest = (await this.executions())[0];
    assert.notEqual(latest.id, this.previousExecution);
    this.execution = latest;
    await this.expectReady();
  }

  async prepareWatch() {
    await this.prepareNative();
    await this.launch();
    await this.waitForEvents(events => events.some(event => event.kind === 'command_start' && event.payload.argv?.includes('watch')));
  }

  async expectReadyWatch() {
    await this.expectReady();
    const events = await this.events();
    const watch = events.find(event => event.kind === 'command_start' && event.payload.argv?.includes('watch'));
    assert.ok(watch);
    assert.ok(!events.some(event => event.kind === 'command_exit' && event.payload.command === watch.payload.command));
  }

  async prepareRespondingTool() {
    await this.prepareNative('slow-application');
    await this.launch();
    await expect.poll(() => {
      try { return this.workload.serviceResponse(this.chat.id, 8080).includes('Directory'); } catch { return false; }
    }, { timeout: WAIT }).toBe(true);
  }

  async checkReadiness() { this.observedStatus = await this.workload.contextStatus(this.chat.id); }
  async expectNotReadyForTool() {
    assert.notEqual(this.observedStatus.body.state, 'ready');
    const execution = (await this.executions()).find(row => row.id === this.execution.id);
    assert.equal(execution.ready, false);
    assert.ok(['starting', 'running'].includes(execution.status));
  }

  async expectApplicationProgress() {
    await expect(this.panel).toContainText(/starting|waiting|application/i);
    await this.expectReadyWatch();
    await this.waitUntilReady();
    await this.expectApplicationOnly();
  }

  async prepareTwo() {
    await this.prepareNative();
    this.otherChat = await this.createOther();
    await this.world.apiClient.editWorkspaceFile(this.chat.id, 'first-only', 'first');
    await this.world.apiClient.editWorkspaceFile(this.otherChat.id, 'second-only', 'second');
  }

  async launchBoth() {
    await this.launchApi();
    await this.expectReady();
    const other = await this.workload.openContext(this.otherChat.id);
    assert.equal(other.body.state, 'ready');
  }

  expectOwnCheckouts() {
    for (const [chat, own, other] of [[this.chat, 'first-only', 'second-only'], [this.otherChat, 'second-only', 'first-only']]) {
      const sandbox = this.workload.inspect(chat.id);
      this.workload.expectOnlyCheckout(sandbox, chat.id);
      assert.ok(this.workload.canRead(sandbox, own));
      this.workload.cannotRead(sandbox, other);
    }
  }

  expectPrivateDaemons() {
    const first = this.workload.nativeDocker(this.chat.id, 'info', '--format', '{{.ID}}');
    const second = this.workload.nativeDocker(this.otherChat.id, 'info', '--format', '{{.ID}}');
    assert.ok(first && second && first !== second);
    assert.notEqual(first, this.workload.docker('info', '--format', '{{.ID}}'));
    this.workload.assertComposeIsolation(this.chat.id, this.otherChat.id);
  }

  expectBothApplications() {
    for (const chat of [this.chat, this.otherChat]) {
      assert.ok(this.workload.serviceResponse(chat.id, 8765).includes('Native preview application'));
      assert.ok(this.workload.composeDetails(chat.id).some(container => container.Name === '/fixed-preview-website'));
      assert.deepEqual(this.workload.inspect(chat.id).HostConfig.PortBindings || {}, {});
    }
    this.expectPrivateDaemons();
  }

  expectNoPlatformPorts() {
    for (const chat of [this.chat, this.otherChat].filter(Boolean)) {
      const sandbox = this.workload.inspect(chat.id);
      assert.deepEqual(sandbox.HostConfig.PortBindings || {}, {});
      const candidates = this.workload.docker('ps', '--filter', `label=sdd.preview.chat-id=${chat.id}`,
        '--filter', `label=sdd.preview.project=${this.world.applicationState.projectName}`,
        '--filter', 'label=com.docker.compose.service', '--format', '{{.ID}}').split('\n').filter(Boolean);
      if (candidates.length) {
        const controller = JSON.parse(this.workload.docker('inspect', `${this.world.applicationState.projectName}-preview-controller-1`))[0];
        const registryName = `/${this.world.applicationState.projectName}-preview-${chat.id}-registry`;
        for (const container of JSON.parse(this.workload.docker('inspect', ...candidates))) {
          const trustedOuter = container.Id === sandbox.Id;
          const trustedRegistry = container.Name === registryName && container.Image === controller.Image;
          assert.ok(trustedOuter || trustedRegistry,
            'Only the exact trusted outer/acquisition containers may inherit platform Compose image-build labels');
        }
      }
      const platformIds = this.workload.docker('ps', '--no-trunc', '--format', '{{.ID}}').split('\n');
      assert.ok(this.workload.composeDetails(chat.id).every(container => !platformIds.includes(container.Id)),
        'Actual project service containers must exist only on the private daemon');
    }
  }

  async preparePlatformEnvironment() {
    await this.prepareNative();
    const controller = JSON.parse(this.workload.docker('inspect', `${this.world.applicationState.projectName}-preview-controller-1`))[0];
    const backend = JSON.parse(this.workload.docker('inspect', `${this.world.applicationState.projectName}-backend-1`))[0];
    assert.ok(controller.Mounts.some(mount => mount.Destination === '/var/run/docker.sock'), 'The platform controller addresses the platform Docker socket');
    assert.ok(backend.Config.Env.some(value => value.startsWith('OPENAI_API_KEY=')));
  }

  expectPrivateDockerConnection() {
    const sandbox = this.workload.inspect(this.chat.id);
    assert.ok(sandbox.Config.Env.includes('DOCKER_HOST=unix:///run/user/1000/docker.sock'));
    assert.notEqual(this.workload.nativeDocker(this.chat.id, 'info', '--format', '{{.ID}}'), this.workload.docker('info', '--format', '{{.ID}}'));
    const commands = (this.execution.workflow || {}).commands || [];
    assert.ok(commands.every(command => !Object.keys(command.env || {}).some(key => key.startsWith('DOCKER_'))));
  }

  async preparePrivilegedDeployment() {
    await this.prepareNative();
    const controller = JSON.parse(this.workload.docker('inspect', `${this.world.applicationState.projectName}-preview-controller-1`))[0];
    assert.ok(controller.Config.Env.includes('PREVIEW_NATIVE_PRIVILEGED=true'), 'This scenario requires the suite-owned trusted privileged deployment');
    this.platformBefore = new Set(this.workload.docker('ps', '-aq').split('\n'));
  }

  expectPrivilegedOuterOnly() {
    assert.equal(this.workload.inspect(this.chat.id).HostConfig.Privileged, true);
    assert.ok(this.workload.composeDetails(this.chat.id).every(container => !container.HostConfig.Privileged));
    const created = this.workload.docker('ps', '-q').split('\n').filter(id => id && !this.platformBefore.has(id));
    for (const id of created) {
      const container = JSON.parse(this.workload.docker('inspect', id))[0];
      if (container.HostConfig.Privileged) assert.equal(container.Config.Labels['sdd.preview.chat-id'], this.chat.id);
    }
  }

  expectRootlessDaemon() {
    assert.equal(this.workload.docker('exec', this.workload.inspect(this.chat.id).Id, 'id', '-u'), '1000');
    const security = JSON.parse(this.workload.nativeDocker(this.chat.id, 'info', '--format', '{{json .SecurityOptions}}'));
    assert.ok(security.some(value => value.includes('rootless')));
  }

  async prepareUnprovisionable() {
    await this.prepareNative();
    const controller = JSON.parse(this.workload.docker('inspect', `${this.world.applicationState.projectName}-preview-controller-1`))[0];
    const entry = controller.Config.Env.find(value => value.startsWith('PREVIEW_NATIVE_IMAGE='));
    this.nativeImage = entry?.slice('PREVIEW_NATIVE_IMAGE='.length);
    assert.ok(this.nativeImage?.startsWith(`${this.world.applicationState.projectName}-`), 'Only the disposable invocation-owned image tag may be made unavailable');
    this.nativeImageId = JSON.parse(this.workload.docker('image', 'inspect', this.nativeImage))[0].Id;
    this.reservedImage = `${this.world.applicationState.projectName}-native-provisioning-reserve:acceptance`;
    this.platformBefore = new Set(this.workload.docker('ps', '-aq').split('\n'));
  }

  async launchUnprovisionable() {
    this.workload.docker('image', 'tag', this.nativeImageId, this.reservedImage);
    try {
      this.workload.docker('image', 'rm', this.nativeImage);
      await this.launchApi();
    } finally {
      this.workload.docker('image', 'tag', this.nativeImageId, this.nativeImage);
      this.workload.docker('image', 'rm', this.reservedImage);
    }
  }

  async expectProvisionFailure() { await this.expectDiagnostic(/image|provision|policy|sandbox/i); }
  expectNoFallback() {
    assert.equal(this.workload.isRunning(this.chat.id), false);
    const created = this.workload.docker('ps', '-aq').split('\n').filter(id => id && !this.platformBefore.has(id));
    assert.deepEqual(created, [], 'Provisioning failure must not create platform project service containers');
  }

  async prepareIdle() {
    await this.prepareNative('output-idle');
    await this.page.goto('about:blank');
    await this.launchApi();
    await this.expectReady();
    // Startup may use more than a minute. The Given is a running preview;
    // begin its five-minute output/idle window only after real Context activity.
    await this.leaveReadyContext();
    this.previousExecution = this.execution.id;
  }

  async expectRemoved() {
    await expect.poll(() => this.workload.docker('ps', '-aq', '--filter', `label=sdd.preview.chat-id=${this.chat.id}`), { timeout: WAIT }).toBe('');
    assert.equal(this.workload.docker('volume', 'ls', '-q', '--filter', `label=sdd.preview.chat-id=${this.chat.id}`), '');
  }

  async expectIdleHistory() { await this.reopenExpired(); await this.expectHistoryAfterIdle(); }

  async removeAndRestartController() {
    await this.prepareNative();
    await this.launchApi();
    await this.expectReady();
    await this.page.goto('about:blank');
    this.oldSandbox = this.workload.inspect(this.chat.id).Id;
    this.workload.docker('rm', '-f', this.oldSandbox);
    this.workload.docker('restart', `${this.world.applicationState.projectName}-preview-controller-1`);
  }

  async reconcile() { await this.waitForExecution(row => row.status === 'interrupted'); await this.reopenExpired(); }
  async expectInterrupted() {
    await expect(this.operation.locator('summary')).toContainText('interrupted', { timeout: WAIT });
    assert.ok((await this.events()).some(event => event.kind === 'status' && event.payload.status === 'interrupted'));
  }

  async expectNoReplacementSandbox() {
    assert.equal(this.workload.isRunning(this.chat.id), false);
    assert.equal((await this.executions()).length, 1);
  }

  async expectInitializationOrder() {
    const events = await this.waitForEvents(rows => rows.some(event => event.kind === 'command_start' && event.payload.argv?.includes('watch')));
    const start = events.find(event => event.kind === 'command_start' && event.payload.argv?.includes('init.py'));
    const exit = events.find(event => event.kind === 'command_exit' && event.payload.command === start.payload.command);
    const watch = events.find(event => event.kind === 'command_start' && event.payload.argv?.includes('watch'));
    assert.ok(start.sequence < exit.sequence && exit.sequence < watch.sequence);
    assert.equal(exit.payload.exit_code, 0);
  }

  async expectCommandsVisible() {
    await this.expandOperation();
    await expect(this.commandOutput).toContainText('init.py');
    await expect(this.commandOutput).toContainText('watch');
    await expect(this.commandOutput).toContainText('first user initialized');
    const events = await this.waitForEvents(rows => rows.some(event => event.kind === 'stdout' && event.payload.command === 1 && event.payload.text?.trim()));
    const output = events.find(event => event.kind === 'stdout' && event.payload.command === 1 && event.payload.text?.trim());
    assert.ok(output, 'The continuing Compose command must expose actual output');
  }

  async expectNativeConfiguration() {
    await this.expectReadyWatch();
    const services = this.workload.composeDetails(this.chat.id);
    assert.ok(['website', 'api', 'db', 'mail', 'admin'].every(name => services.some(container => container.Config.Labels['com.docker.compose.service'] === name)));
    const db = services.find(container => container.Config.Labels['com.docker.compose.service'] === 'db');
    assert.equal(db.State.Health.Status, 'healthy');
    assert.ok(db.Mounts.some(mount => mount.Type === 'volume' && mount.Destination === '/var/lib/postgresql/data'));
    const website = services.find(container => container.Config.Labels['com.docker.compose.service'] === 'website');
    assert.ok(website.HostConfig.PortBindings['8765/tcp'].some(binding => binding.HostPort === '8765'));
    assert.ok((await this.events()).filter(event => event.kind === 'command_start').every(event =>
      event.payload.argv?.includes('watch') || event.payload.argv?.includes('run')));
  }

  async expectUnchanged() { assert.deepEqual(await this.checkoutFiles(Object.keys(this.savedFiles)), this.savedFiles); }
  async launchInitializationFailure() { await this.launchApi(); await this.waitForExecution(row => row.status === 'failed'); }
  async expectNoLaterStartup() {
    const events = await this.events();
    assert.ok(events.some(event => event.kind === 'command_exit' && event.payload.exit_code === 17));
    assert.ok(!events.some(event => event.kind === 'command_start' && event.payload.argv?.includes('watch')));
  }
  async expectInitializationFailure() {
    await this.expandOperation();
    await expect(this.commandOutput).toContainText('init.py');
    await expect(this.commandOutput).toContainText('17');
    await expect(this.operation.locator('summary')).toContainText('failed');
  }
  async expectOnlyFailedResourcesGone() {
    await this.expectRemoved();
    assert.ok(this.workload.isRunning(this.otherChat.id));
    assert.ok(this.workload.serviceResponse(this.otherChat.id, 8765).includes('Native preview application'));
  }

  async expectUsableApplication() { await this.waitUntilReady(); await this.expectApplicationOnly(); }
  async createApplicationItem() { await this.workload.loginAndCreateNativeItem(this.frame); }
  expectDatabaseItem() {
    const api = this.workload.serviceContainer(this.chat.id, 8766);
    const rows = this.workload.nativeDocker(this.chat.id, 'exec', api, 'python', '-c',
      "from db import query; print(query('SELECT name FROM items'))");
    assert.ok(rows.includes(this.workload.nativeItem));
  }

  async addResourceProcesses() {
    this.resourceBefore = this.workload.inspect(this.chat.id).HostConfig;
    this.resourceContainer = this.workload.nativeDocker(this.chat.id, 'compose', '--project-directory', '/workspace', 'run', '-d', '--no-deps', 'api',
      'python', '-u', '-c', 'import subprocess,time; children=[subprocess.Popen(["python","-c","import time; time.sleep(90)"]) for _ in range(3)]; print("aggregate-resource-probe",flush=True); time.sleep(90)').trim();
    this.workload.nativeDocker(this.chat.id, 'compose', '--project-directory', '/workspace', 'build', 'api');
  }
  expectAggregateBudget() {
    const sandbox = this.workload.inspect(this.chat.id);
    this.workload.expectSandbox(sandbox);
    for (const key of ['Memory', 'MemorySwap', 'NanoCpus', 'PidsLimit', 'Tmpfs']) assert.deepEqual(sandbox.HostConfig[key], this.resourceBefore[key]);
    const processes = this.workload.docker('top', sandbox.Id, '-eo', 'pid,ppid,args');
    assert.ok(processes.includes('aggregate-resource-probe'), 'Nested project processes must be in the outer sandbox process tree/cgroup');
    assert.ok(this.workload.composeDetails(this.chat.id).length > 5);
    const probe = `from pathlib import Path
import json, time
root = Path('/sys/fs/cgroup')
def throttled():
    return int(dict(line.split() for line in (root / 'cpu.stat').read_text().splitlines())['nr_throttled'])
before = throttled()
deadline = time.monotonic() + 1.5
while time.monotonic() < deadline:
    pass
print(json.dumps({
    'cpu': (root / 'cpu.max').read_text().strip(),
    'memory': (root / 'memory.max').read_text().strip(),
    'swap': (root / 'memory.swap.max').read_text().strip(),
    'pids': (root / 'pids.max').read_text().strip(),
    'throttled': throttled() - before,
}))`;
    for (const container of [this.resourceContainer, this.workload.serviceContainer(this.chat.id, 8766)]) {
      const limits = JSON.parse(this.workload.nativeDocker(this.chat.id, 'exec', container, 'python', '-c', probe));
      const [quota, period] = limits.cpu.split(' ').map(Number);
      assert.equal(quota / period, sandbox.HostConfig.NanoCpus / 1e9, 'Nested processes must see the actual outer CPU quota');
      assert.equal(Number(limits.memory), sandbox.HostConfig.Memory, 'Nested processes must see the actual aggregate memory limit');
      assert.equal(Number(limits.swap), sandbox.HostConfig.MemorySwap - sandbox.HostConfig.Memory);
      assert.equal(Number(limits.pids), sandbox.HostConfig.PidsLimit, 'Additional services must share the actual outer process limit');
      assert.ok(limits.throttled > 0, 'The kernel must enforce the CPU budget on nested project work');
    }
    this.expectNoPlatformPorts();
  }

  async launchLocal() {
    await this.workload.selectInstructions(this.workload.documentedPlan());
    await this.launchAndWait();
    if (this.fixtureKind !== 'local-timeout') await this.expectReady();
  }
  expectLocalServices() {
    assert.equal(this.workload.installedDependency(this.chat.id), true);
    assert.match(this.workload.serviceResponse(this.chat.id, 8765), /API reachable true/);
    assert.match(this.workload.serviceResponse(this.chat.id, 8766), /API response/);
  }
  expectLocalSandbox() {
    this.workload.expectSandbox(this.workload.inspect(this.chat.id));
    this.workload.expectPreviewTools(this.chat.id);
    this.workload.expectNoExternalNetwork(this.chat.id);
  }
  async expectLocalTimeout() {
    await this.expectDiagnostic(/fail|time|ready/i);
    assert.equal(this.workload.isRunning(this.chat.id), false);
    assert.equal(this.workload.isRunning(this.otherChat.id), true);
  }

  async prepareSwagger() {
    await this.prepareLocal();
    await this.writeFiles({ 'README.md': 'Run python -m http.server 8766 in api on port 8766. Swagger UI is at /docs.', 'api/docs': 'Swagger UI' });
    await this.workload.selectInstructions({ setup: [], website: null, api: { cwd: 'api', argv: ['python', '-m', 'http.server', '8766'], port: 8766, path: '/' } });
  }
  async expectSwagger() {
    const status = await this.workload.contextStatus(this.chat.id);
    assert.equal(status.body.state, 'ready');
    assert.equal(status.body.initial_port, '8766');
    assert.equal(status.body.initial_path, '/docs');
    const browser = await this.workload.browserContext(this.chat.id, 8766);
    const response = await browser.get('/docs');
    assert.equal(response.status(), 200);
    assert.match(await response.text(), /Swagger UI/);
  }

  async preparePlainCommands() {
    await this.prepareLocal();
    await this.writeFiles({ 'compose.yml': 'services:\n  website:\n    network_mode: host\n' });
    this.savedFiles = await this.checkoutFiles(['compose.yml']);
  }
  async expectPlainCommands() {
    await this.expectReady();
    assert.equal(this.workload.isNative(this.chat.id), false);
    await this.expectUnchanged();
    assert.ok(!(this.execution.workflow.commands || []).some(command => command.argv?.includes('compose')));
  }

  async expectUnsafeRejected() { await this.expectDiagnostic(/host|namespace|mount|control|unsafe/i); await this.expectRemoved(); }

  async startOther() {
    this.otherChat ??= await this.createOther();
    if (!this.workload.isRunning(this.otherChat.id)) await this.workload.openContext(this.otherChat.id);
  }
  expectApplicationApi() {
    const value = JSON.parse(this.workload.serviceResponse(this.chat.id, 8765, '/api/health'));
    assert.equal(value.ready, true, 'The website must reach the database-backed API by its Compose service name');
  }
  expectResourceLimits() { this.workload.expectSandbox(this.workload.inspect(this.chat.id)); }
  async prepareMissing() { await this.prepareNative('missing'); await this.workload.selectInstructions(null); }

  async visibleActivity() {
    const heartbeat = this.page.waitForResponse(response => response.request().method() === 'POST' &&
      new URL(response.url()).pathname === `/api/v1/develop/chats/${this.chat.id}/preview/activity`, { timeout: WAIT });
    await this.world.developPage.open(this.token);
    await this.world.developPage.selectChat(this.chat.title);
    await this.open();
    assert.equal((await heartbeat).status(), 200);
    await this.waitUntilReady();
    assert.equal(this.workload.isRunning(this.chat.id), true);
  }
  async deleteSelected() { await this.workload.deleteChat(this.chat.id); }
  async expectOtherRunning() {
    assert.equal(this.workload.isRunning(this.chat.id), false);
    assert.equal(this.workload.isRunning(this.otherChat.id), true);
    assert.ok(this.workload.serviceResponse(this.otherChat.id, 8765).includes('Native preview application'));
  }
  async expectChatAvailable() {
    const rows = await this.world.apiClient.listDevelopmentChats(this.token);
    assert.ok(rows.data.some(row => row.id === this.chat.id));
  }
}


function nativePage(world) {
  world.nativePreviewPage ??= new NativePreviewPage(world);
  world.previewExecutionPage = world.nativePreviewPage;
  world.developContextPage ??= world.nativePreviewPage;
  return world.nativePreviewPage;
}
module.exports = { NativePreviewPage, nativePage };
