const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { expect } = require('@playwright/test');
const { configureDemoRepository } = require('../../features/support/app-lifecycle.js');
const { DevelopContextPage } = require('./develop-context-page.js');

const WAIT = 240_000;
const TERMINAL = new Set(['failed', 'stopped', 'interrupted']);
const TRUNCATED = new Set(['truncated', 'output_truncated', 'gap']);

class PreviewExecutionPage extends DevelopContextPage {
  get chat() { return this.world.developmentChat; }
  get token() { return this.world.userToken; }
  get conversation() { return this.page.getByRole('region', { name: 'Conversation', exact: true }); }
  get operation() {
    const entries = this.conversation.getByRole('article', { name: 'Preview execution', exact: true });
    return this.execution ? this.conversation.locator(`article[data-execution-id="${this.execution.id}"]`) : entries;
  }
  get commandOutput() { return this.operation.getByRole('log', { name: 'Preview command output' }); }

  async request(action, method = 'get', token = this.token, options = {}) {
    return this.world.apiClient.request(token, method,
      `/api/v1/develop/chats/${this.chat.id}/preview/${action}`, options);
  }

  async json(action) {
    const response = await this.request(action);
    assert.equal(response.status(), 200, `Preview ${action} returned ${response.status()}`);
    return response.json();
  }

  async executions() { return (await this.json('executions')).data; }

  async events(after = 0) {
    assert.ok(this.execution, 'A real execution must exist before reading its events');
    const events = [];
    let cursor = after;
    for (;;) {
      const page = await this.json(`executions/${this.execution.id}/events?after=${cursor}`);
      events.push(...page.data);
      if (!page.has_more) break;
      const next = page.next_sequence ?? page.data.at(-1)?.sequence;
      assert.ok(next > cursor, 'Replay pagination must advance');
      cursor = next;
    }
    assert.equal(new Set(events.map(event => event.sequence)).size, events.length, 'Replay must not repeat sequence numbers');
    assert.ok(events.every((event, index) => event.execution_id === this.execution.id &&
      event.sequence > (index ? events[index - 1].sequence : after)), 'Replay must remain owner/execution scoped and ordered');
    return events;
  }

  async waitForExecution(predicate, description = 'execution state') {
    try {
      await expect.poll(async () => {
        const rows = await this.executions();
        const execution = this.execution ? rows.find(row => row.id === this.execution.id) : rows.at(-1);
        if (!execution) return false;
        this.execution = execution;
        if (predicate(execution)) return true;
        assert.ok(!TERMINAL.has(execution.status), `Execution became ${execution.status} before ${description}`);
        return false;
      }, { timeout: WAIT, message: `Waiting for ${description}` }).toBe(true);
    } catch (error) {
      const events = this.execution ? await this.events() : [];
      throw new Error(`${error.message}\nExecution: ${JSON.stringify(this.execution)}\nPersisted output: ${JSON.stringify(events).slice(-20000)}`, { cause: error });
    }
    return this.execution;
  }

  async waitForEvents(predicate, description = 'persisted preview output') {
    let observed;
    await expect.poll(async () => {
      observed = await this.events();
      return Boolean(predicate(observed));
    }, { timeout: WAIT, message: `Waiting for ${description}` }).toBe(true);
    return observed;
  }

  async prepare({ mode = 'normal', selected = false } = {}) {
    await configureDemoRepository(true);
    this.world.userToken ??= await this.world.apiClient.authenticateSuperuser();
    if (!selected || !this.world.developmentChat) {
      this.world.developmentChat = await this.world.apiClient.createDevelopmentChat(
        this.token, `Preview execution ${randomUUID()}`);
    }
    const workspace = await this.world.apiClient.developmentWorkspace(this.token, this.chat.id);
    assert.equal(workspace.status(), 200);
    if (!(await workspace.json()).ready) {
      const setup = await this.world.apiClient.setupDevelopmentWorkspace(this.token, this.chat.id);
      assert.equal(setup.status(), 200, await setup.text());
    }
    const files = await this.world.previewWorkloadPage.prepareNativeCompose(this.chat.id);
    this.secret = `acceptance-project-secret-${randomUUID()}`;
    this.markup = '<img src=x onerror="window.__previewOutputExecuted=true"><script>window.__previewOutputExecuted=true</script>**literal preview output**';
    const before = `import os, sys, time\nprint('acceptance initialization entered', flush=True)\n`;
    const live = `for index in range(${mode === 'live' ? 48 : 12}):\n    print(f'acceptance stdout tick {index:03d}', flush=True)\n    print(f'acceptance stderr tick {index:03d}', file=sys.stderr, flush=True)\n    time.sleep(0.5)\n`;
    const variants = {
      normal: before + live + files['api/init.py'],
      live: before + live + files['api/init.py'],
      failed: before + "print('acceptance initialization diagnostic ' + os.environ['PREVIEW_EXECUTION_SECRET'], file=sys.stderr, flush=True)\nsys.exit(17)\n",
      retention: before + "for index in range(1024):\n    print('retention output ' + str(index) + ' ' + 'x' * 2048, flush=True)\nprint('acceptance retained final diagnostic', file=sys.stderr, flush=True)\nsys.exit(23)\n",
      secret: before + "secret = os.environ['PREVIEW_EXECUTION_SECRET']\ncut = len(secret) // 2\nsys.stdout.write('split secret: ' + secret[:cut]); sys.stdout.flush()\ntime.sleep(0.5)\nsys.stdout.write(secret[cut:] + '\\n'); sys.stdout.flush()\nsys.exit(29)\n",
      markup: before + `print(${JSON.stringify(`\u001b[31m${this.markup}\u001b[0m\u001b]52;c;ignored\u0007`)}, flush=True)\nsys.exit(31)\n`,
      missing: before + files['api/init.py'],
    };
    assert.ok(variants[mode], `Unknown real-project fixture mode: ${mode}`);
    await this.world.apiClient.withWorkspaceFileBatch(this.chat.id, async () => {
      await this.world.apiClient.editWorkspaceFile(this.chat.id, '.env', files['.env'] + `PREVIEW_EXECUTION_SECRET=${this.secret}\n`);
      await this.world.apiClient.editWorkspaceFile(this.chat.id, 'api/init.py', variants[mode]);
      if (mode === 'missing') {
        await this.world.apiClient.editWorkspaceFile(this.chat.id, 'README.md', '# Project overview\nStartup instructions have not been documented.\n');
      }
    });
    this.world.previewWorkloadPage.chatIds.push(this.chat.id);
    if (mode === 'missing') await this.world.apiClient.configureFakeLlm({ plan: null });
    this.beforeMessages = (await this.world.apiClient.listDevelopmentMessages(this.token, this.chat.id)).data;
    this.beforeModelRequests = (await this.world.apiClient.fakeLlmRequests()).length;
    this.launchRequests = [];
    this.outputRequests = [];
    this.page.on('request', request => {
      const path = new URL(request.url()).pathname;
      if (request.method() === 'POST' && path === `/api/v1/develop/chats/${this.chat.id}/preview/launch`) this.launchRequests.push(request);
      if (path.startsWith(`/api/v1/develop/chats/${this.chat.id}/preview/executions/`) && path.endsWith('/stream')) this.outputRequests.push(request);
    });
    await this.world.developPage.open(this.token);
    if ((this.page.viewportSize()?.width ?? 1440) >= 768) await this.world.developPage.selectChat(this.chat.title);
    this.mode = mode;
  }

  async prepareSmallScreen() {
    await this.prepare({ selected: true });
    await this.open();
  }

  async expectLaunchBesideExpand() {
    const launch = this.panel.getByRole('button', { name: 'Launch preview', exact: true });
    const expand = this.panel.getByRole('button', { name: 'Expand Context', exact: true });
    await expect(launch).toBeVisible();
    await expect(expand).toBeVisible();
    await expect(launch).toBeEnabled();
    const [left, right] = await Promise.all([launch.boundingBox(), expand.boundingBox()]);
    assert.ok(left && right);
    assert.ok(Math.abs(left.y - right.y) <= 4 && left.x + left.width <= right.x + 2,
      'Launch and Expand must be adjacent on the same row');
    await this.expectNoPageOverflow();
  }

  async expectNotStarted() {
    assert.equal(this.launchRequests.length, 0, 'Opening Context must not submit Launch');
    assert.deepEqual(await this.executions(), [], 'Read-only Context must not record a startup attempt');
    assert.equal(this.world.previewWorkloadPage.isRunning(this.chat.id), false);
    await expect(this.panel.locator('iframe[title="Development preview"]')).toHaveCount(0);
  }

  async expectConversationAlongside() {
    await expect(this.panel).toBeVisible();
    await expect(this.conversation).toBeVisible();
    const [chat, panel] = await Promise.all([this.conversation.boundingBox(), this.panel.boundingBox()]);
    assert.ok(chat && panel);
    if ((this.page.viewportSize()?.width ?? 1440) >= 1024) assert.ok(chat.x + chat.width <= panel.x + 1);
    await expect(this.conversation.getByRole('textbox', { name: 'Exploration message' })).toBeVisible();
  }

  async launch() {
    await this.open();
    const response = this.page.waitForResponse(response => response.request().method() === 'POST' &&
      new URL(response.url()).pathname === `/api/v1/develop/chats/${this.chat.id}/preview/launch`, { timeout: WAIT });
    await this.panel.getByRole('button', { name: 'Launch preview', exact: true }).click();
    this.launchResponse = await response;
    assert.equal(this.launchResponse.status(), 200, await this.launchResponse.text());
    const result = await this.launchResponse.json();
    assert.ok(result.execution?.id, 'Launch must return its durable execution identity');
    this.execution = result.execution;
  }

  async expectNoApproval() {
    await expect(this.page.getByRole('dialog')).toHaveCount(0);
    await expect(this.page.getByRole('button', { name: /approve.*preview|confirm.*launch/i })).toHaveCount(0);
    await this.waitForEvents(events => events.some(event => event.kind === 'command_start'));
  }

  async expectLaunchPending() {
    const launch = this.panel.getByRole('button', { name: /^(Launching|Launch) preview$/ });
    await expect(launch).toBeDisabled();
    assert.equal(this.launchRequests.length, 1);
    await this.waitForExecution(execution => ['starting', 'running'].includes(execution.status));
    await expect(launch).toBeDisabled();
  }

  async expandOperation() {
    await expect(this.operation).toHaveCount(1, { timeout: WAIT });
    const details = this.operation.locator('details');
    if (!(await details.evaluate(element => element.open))) await this.operation.locator('summary').click();
    await expect(this.commandOutput).toBeVisible();
  }

  async expectLiveOutput() {
    await this.waitForExecution(execution => ['starting', 'running'].includes(execution.status));
    await this.expandOperation();
    await expect(this.commandOutput).toContainText('acceptance stdout tick 000', { timeout: WAIT });
    await expect(this.commandOutput).toContainText('acceptance stderr tick 000', { timeout: WAIT });
    const events = await this.events();
    assert.ok(events.some(event => event.kind === 'command_start' && event.payload.argv?.includes('init.py')));
    assert.ok(!events.some(event => event.kind === 'command_exit'), 'Initialization must still be running when its output is displayed');
    await this.expectConversationAlongside();
    await expect.poll(() => this.outputRequests.length).toBeGreaterThan(0);
    assert.ok(this.outputRequests.every(request => request.headers().authorization === `Bearer ${this.token}`));
    this.displayedEvents = events;
  }

  async expectNoAgentTurn({ instructionResolver = false } = {}) {
    const messages = (await this.world.apiClient.listDevelopmentMessages(this.token, this.chat.id)).data;
    assert.deepEqual(messages, this.beforeMessages, 'Preview execution must not invent conversation messages');
    assert.equal((await this.world.apiClient.currentAgentTurn(this.token, this.chat.id)).status(), 404);
    const modelRequests = (await this.world.apiClient.fakeLlmRequests()).slice(this.beforeModelRequests);
    if (instructionResolver) {
      // The unchanged non-Compose contract permits README extraction, not an
      // agent turn or a guessed replacement workflow.
      assert.equal(modelRequests.length, 1);
      assert.equal(modelRequests[0].selection?.phase, 'planner');
    } else {
      assert.equal(modelRequests.length, 0, 'Native preview launch must not invoke an agent model');
    }
    await expect(this.conversation.getByRole('article', { name: 'Streaming assistant response' })).toHaveCount(0);
    if (this.execution) await expect(this.operation.locator('.sr-only')).toHaveCount(0);
  }

  async expectRecorded() {
    await this.waitForExecution(() => true);
    assert.equal(this.execution.chat_id, this.chat.id);
    assert.ok(this.execution.created_at && this.execution.updated_at);
    assert.ok(this.execution.workflow ?? this.execution.workflow_snapshot);
    await this.expandOperation();
  }

  async waitUntilReady() {
    if (!this.execution) await this.launch();
    await this.waitForExecution(execution => execution.ready && execution.status === 'running', 'running watch with a ready application');
    await expect(this.frame.getByRole('heading', { name: 'Native preview application', exact: true })).toBeVisible({ timeout: WAIT });
  }

  async expectApplicationOnly() {
    await expect(this.frame.getByRole('heading', { name: 'Native preview application', exact: true })).toBeVisible();
    await expect(this.panel.getByRole('link', { name: /mailpit|adminer|mail tool|database administration/i })).toHaveCount(0);
    await expect(this.panel.getByRole('combobox')).toHaveCount(0);
    await expect(this.panel.locator('iframe[title="Development preview"]')).toHaveCount(1);
  }

  async launchAndKeepMobileConversation() {
    await this.launch();
    await this.waitUntilReady();
    await this.panel.getByRole('button', { name: 'Close panel', exact: true }).click();
    await expect(this.conversation).toBeVisible();
    const input = this.conversation.getByRole('textbox', { name: 'Exploration message' });
    await input.scrollIntoViewIfNeeded();
    await expect(input).toBeInViewport();
    await input.fill('Unsent message while the preview is running');
    await expect(this.conversation.getByRole('button', { name: 'Send exploration' })).toBeEnabled();
    await input.fill('');
    await this.expectNoPageOverflow();
  }

  async prepareActive() {
    await this.prepare({ mode: 'live' });
    await this.launch();
    await this.expectLiveOutput();
  }

  async refresh() {
    this.savedExecutionId = this.execution.id;
    this.savedEvents = await this.events();
    this.savedCursor = this.savedEvents.at(-1)?.sequence ?? 0;
    this.savedLaunchCount = this.launchRequests.length;
    await this.page.reload();
    await this.world.developPage.expectWorkspaceVisible();
    await this.open();
    await this.expandOperation();
  }

  async expectRestored() {
    await expect(this.operation).toHaveCount(1);
    await expect(this.commandOutput).toContainText('acceptance stdout tick 000');
    assert.equal(this.execution.id, this.savedExecutionId);
    assert.equal(this.launchRequests.length, this.savedLaunchCount);
  }

  async expectMoreOutputOnce() {
    const savedSequences = new Set(this.savedEvents.map(event => event.sequence));
    const events = await this.waitForEvents(rows => rows.some(event => !savedSequences.has(event.sequence) &&
      ['stdout', 'stderr'].includes(event.kind) && event.payload.text?.includes('acceptance stdout tick')));
    const output = events.filter(event => event.kind === 'stdout').map(event => event.payload.text ?? '').join('');
    const markers = output.match(/acceptance stdout tick \d{3}/g) ?? [];
    assert.ok(markers.length > 1);
    const latest = markers.at(-1);
    await expect(this.commandOutput).toContainText(latest, { timeout: WAIT });
    const visible = await this.commandOutput.textContent();
    for (const marker of markers) assert.equal(visible.split(marker).length - 1, 1, `Output marker ${marker} must appear once`);
    assert.equal(events.filter(event => event.kind === 'command_start' && event.payload.argv?.includes('init.py')).length, 1,
      'Reattachment must not execute initialization again');
    assert.equal((await this.executions()).length, 1);
    assert.equal(this.launchRequests.length, this.savedLaunchCount);
  }

  async prepareFailed() {
    await this.prepare({ mode: 'failed' });
    await this.launch();
    await this.waitForExecution(execution => execution.status === 'failed');
    await expect.poll(() => this.world.previewWorkloadPage.isRunning(this.chat.id), { timeout: WAIT }).toBe(false);
  }

  async revisit() {
    this.savedLaunchCount = this.launchRequests.length;
    await this.world.developPage.open(this.token);
    await this.expandOperation();
  }

  async expectFailureVisible() {
    await expect(this.commandOutput).toContainText('init.py', { timeout: WAIT });
    await expect(this.commandOutput).toContainText('acceptance initialization diagnostic');
    await expect(this.commandOutput).toContainText('[REDACTED]');
    await expect(this.commandOutput).toContainText('17');
    await expect(this.operation.locator('summary')).toContainText('failed');
    assert.equal((await this.commandOutput.textContent()).includes(this.secret), false, 'Known project value must be masked');
  }

  async expectNoReplacement() {
    assert.equal(this.launchRequests.length, this.savedLaunchCount);
    assert.equal((await this.executions()).length, 1);
    assert.equal(this.world.previewWorkloadPage.isRunning(this.chat.id), false);
  }

  async concurrentLaunches() {
    this.concurrentResults = await Promise.all([1, 2].map(async () => {
      const response = await this.request('launch', 'post', this.token, { data: {} });
      assert.equal(response.status(), 200, await response.text());
      return response.json();
    }));
    assert.ok(this.concurrentResults.every(result => result.execution?.id));
    this.execution = this.concurrentResults[0].execution;
  }

  async expectSingleOwner() {
    await this.waitForExecution(execution => execution.status === 'running');
    assert.equal((await this.executions()).filter(execution => ['starting', 'running'].includes(execution.status)).length, 1);
    assert.equal(this.world.previewWorkloadPage.containerIds(this.chat.id).length, 1,
      'Exactly one outer sandbox may own this chat');
  }

  async expectInitializationOnce() {
    const events = await this.waitForEvents(rows => rows.some(event => event.kind === 'command_exit'));
    assert.equal(events.filter(event => event.kind === 'command_start' && event.payload.argv?.includes('init.py')).length, 1);
    const text = events.filter(event => event.kind === 'stdout').map(event => event.payload.text ?? '').join('');
    assert.equal(text.split('acceptance initialization entered').length - 1, 1);
  }

  expectSameLaunchIdentity() {
    assert.equal(this.concurrentResults[0].execution.id, this.concurrentResults[1].execution.id);
  }

  async prepareOtherOwnerOutput() {
    await this.prepareActive();
    const user = await this.world.apiClient.createUser();
    this.otherToken = await this.world.apiClient.authenticate(user.email, user.password);
  }

  async requestAsOtherOwner() {
    const actions = [
      ['launch', 'post'], ['context', 'get'], ['status', 'get'], ['executions', 'get'],
      [`executions/${this.execution.id}/events?after=0`, 'get'],
      [`executions/${this.execution.id}/stream?after=0`, 'get'],
    ];
    this.denied = [];
    for (const [action, method] of actions) {
      const response = await this.request(action, method, this.otherToken, { data: method === 'post' ? {} : undefined, timeout: 5000 });
      this.denied.push({ status: response.status(), body: await response.text() });
    }
  }

  expectDenied() { assert.ok(this.denied.every(response => [403, 404].includes(response.status))); }
  expectNoDisclosure() {
    assert.ok(this.denied.every(response => !response.body.includes(this.execution.id) &&
      !response.body.includes('acceptance stdout') && !response.body.includes('docker compose')));
  }

  async expectDisplayedDurable() {
    const durable = await this.events();
    for (const event of this.displayedEvents) assert.deepEqual(durable.find(row => row.sequence === event.sequence), event);
  }

  async disconnect() {
    await this.prepareActive();
    this.savedEvents = await this.events();
    this.savedCursor = this.savedEvents.at(-1).sequence;
    this.savedExecutionId = this.execution.id;
    this.savedLaunchCount = this.launchRequests.length;
    await this.page.goto('about:blank');
    await this.waitForEvents(events => events.some(event => event.sequence > this.savedCursor && event.kind === 'stdout'));
  }

  async captureStream(after, receivedEnough) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), WAIT);
    const events = [];
    let reader;
    try {
      const url = new URL(`/api/v1/develop/chats/${this.chat.id}/preview/executions/${this.execution.id}/stream?after=${after}`,
        this.world.applicationState.baseUrl);
      const response = await fetch(url, { headers: { Authorization: `Bearer ${this.token}`, Accept: 'text/event-stream' }, signal: controller.signal });
      assert.equal(response.status, 200);
      assert.ok(response.body);
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      while (!controller.signal.aborted) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let match = /\r?\n\r?\n/.exec(buffer);
        while (match) {
          const frame = buffer.slice(0, match.index).replace(/\r\n/g, '\n');
          buffer = buffer.slice(match.index + match[0].length);
          if (frame.split('\n').includes('event: preview-event')) {
            const data = frame.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
            events.push(JSON.parse(data));
          }
          match = /\r?\n\r?\n/.exec(buffer);
        }
        if (receivedEnough(events)) break;
      }
      assert.ok(receivedEnough(events), 'The authenticated stream must deliver the required persisted and live events');
      return events;
    } finally {
      clearTimeout(timer);
      controller.abort();
      await reader?.cancel().catch(() => undefined);
    }
  }

  async receiveStreamAfterCursor() {
    this.replayBacklog = await this.events(this.savedCursor);
    assert.ok(this.replayBacklog.length, 'Disconnect must leave persisted output to replay');
    this.replayWatermark = this.replayBacklog.at(-1).sequence;
    this.reconnectedEvents = await this.captureStream(this.savedCursor, events => events.some(event =>
      event.sequence > this.replayWatermark && event.kind === 'stdout' && event.payload.text?.includes('acceptance stdout tick')));
    await this.world.developPage.open(this.token);
    await this.open();
    await this.expandOperation();
    this.savedEvents = await this.events();
  }

  async expectReplayedOrder() {
    assert.ok(this.reconnectedEvents.every((event, index) => event.execution_id === this.execution.id &&
      event.sequence > (index ? this.reconnectedEvents[index - 1].sequence : this.savedCursor)));
    assert.deepEqual(this.reconnectedEvents.filter(event => event.sequence <= this.replayWatermark), this.replayBacklog,
      'Reconnect must replay the entire persisted backlog, not merely an ordered subset');
    const durable = await this.events(this.savedCursor);
    const lastReceived = this.reconnectedEvents.at(-1).sequence;
    assert.deepEqual(this.reconnectedEvents, durable.filter(event => event.sequence <= lastReceived),
      'Replay-to-live delivery must not omit intervening persisted events');
  }

  async prepareRetention() {
    await this.prepare({ mode: 'retention' });
    await this.launch();
    await this.waitForExecution(execution => TERMINAL.has(execution.status));
    this.retainedEvents = await this.events();
    assert.ok(this.retainedEvents.some(event => TRUNCATED.has(event.kind)), 'The real command must exceed actual retention bounds');
  }

  async displayRetained() { await this.revisit(); }

  async expectTruncation() {
    assert.ok(this.retainedEvents.some(event => TRUNCATED.has(event.kind)));
    await expect(this.operation).toContainText(/output truncated|output.*omitted/i);
  }

  async expectFinalStatusRetained() {
    const events = await this.events();
    assert.ok(events.some(event => event.kind === 'command_exit' && event.payload.exit_code === 23));
    assert.ok(events.some(event => event.kind === 'status' && TERMINAL.has(event.payload.status)));
    await expect(this.commandOutput).toContainText('23');
    await expect(this.operation.locator('summary')).toContainText(this.execution.status);
  }

  async printSplitSecret() {
    await this.launch();
    this.secretStreamEvents = await this.captureStream(0, events => events.some(event =>
      event.kind === 'status' && TERMINAL.has(event.payload.status)));
    await this.waitForExecution(execution => TERMINAL.has(execution.status));
    await this.expandOperation();
  }

  async expectSecretMasked() {
    const events = await this.events();
    const text = events.filter(event => ['stdout', 'stderr'].includes(event.kind)).map(event => event.payload.text ?? '').join('');
    assert.equal(JSON.stringify(events).includes(this.secret), false, 'Stored preview events must not contain a known secret');
    assert.ok(text.includes('[REDACTED]'), 'Split project-secret output must be masked, not silently discarded');
    const delivered = this.secretStreamEvents.filter(event => ['stdout', 'stderr'].includes(event.kind))
      .map(event => event.payload.text ?? '').join('');
    assert.equal(JSON.stringify(this.secretStreamEvents).includes(this.secret), false, 'Raw live events must not contain a known secret');
    assert.equal(delivered.includes(this.secret), false, 'Concatenating live chunks must not reconstruct the secret');
    assert.ok(delivered.includes('[REDACTED]'), 'The live stream must actually deliver the masked split-secret output');
    assert.equal((await this.commandOutput.textContent()).includes(this.secret), false, 'Delivered operation output must mask the secret');
  }

  async expectLogsMasked() {
    await this.expectSecretMasked();
    const backend = spawnSync('docker', ['logs', `${this.world.applicationState.projectName}-backend-1`],
      { encoding: 'utf8', timeout: 10_000, maxBuffer: 8 * 1024 * 1024 });
    assert.equal(backend.status, 0, 'Operational backend logs must be readable for the redaction assertion');
    const logs = this.world.previewWorkloadPage.controllerLogs() + (backend.stdout || '') + (backend.stderr || '');
    assert.equal(logs.includes(this.secret), false, 'Operational logs must mask known project values');
  }

  async expectInstructionFailure() {
    await this.waitForExecution(execution => execution.status === 'failed');
    await this.expandOperation();
    await expect(this.operation).toContainText(/provide a complete startup command|checkout-local instruction pointer/i);
    assert.ok((await this.events()).some(event => event.kind === 'status' && event.payload.status === 'failed' && event.payload.reason));
    await this.expectNoAgentTurn({ instructionResolver: true });
  }

  async expectNothingStarted() {
    assert.ok(!(await this.events()).some(event => event.kind === 'command_start'));
    assert.equal(this.world.previewWorkloadPage.isRunning(this.chat.id), false);
  }

  async displayMarkup() {
    await this.launch();
    await this.waitForExecution(execution => TERMINAL.has(execution.status));
    await this.expandOperation();
  }

  async expectSafeText() {
    await expect(this.commandOutput).toContainText(this.markup);
    await expect(this.commandOutput.locator('script, img, strong, a')).toHaveCount(0);
    assert.equal(/[\u001b\u009b\u009d]/.test(await this.commandOutput.textContent()), false);
    assert.ok((await this.events()).some(event => event.payload.text?.includes(this.markup)), 'Markup must originate in real command output');
  }

  async expectNoOutputExecution() {
    assert.equal(await this.page.evaluate(() => Boolean(window.__previewOutputExecuted)), false);
    await this.expectNoAgentTurn();
  }
}

module.exports = { PreviewExecutionPage };
