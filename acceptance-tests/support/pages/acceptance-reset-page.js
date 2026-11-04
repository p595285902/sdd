'use strict';

const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const lifecycle = require('../../features/support/app-lifecycle.js');

const snapshotScript = `
import hashlib, json, os
from pathlib import Path
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, select
from app.core.config import settings
from app.core.db import engine
from app.models import User
inspector = inspect(engine)
with Session(engine) as session:
    records = {}
    for table in SQLModel.metadata.sorted_tables:
        rows = [dict(row._mapping) for row in session.connection().execute(table.select())]
        encoded = sorted(json.dumps(row, sort_keys=True, default=str) for row in rows)
        records[table.name] = {"count": len(rows), "digest": hashlib.sha256(json.dumps(encoded).encode()).hexdigest()}
    users = [{"email": u.email, "is_active": u.is_active, "is_superuser": u.is_superuser, "limit": u.concurrent_agent_turn_limit} for u in session.exec(select(User)).all()]
    versions = list(session.connection().execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars())
files = {}
roots = {}
for name, root in (("workspace", settings.DEVELOP_WORKSPACE_ROOT), ("agent", settings.ACCEPTANCE_AGENT_ROOT)):
    root = Path(root)
    roots[name] = {"exists": root.is_dir(), "device": root.stat().st_dev, "inode": root.stat().st_ino}
    entries = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for child in dirs + names:
            target = Path(directory) / child
            relative = str(target.relative_to(root))
            if relative == ".acceptance-owner.json": continue
            if target.is_symlink(): entries[relative] = {"link": os.readlink(target)}
            elif target.is_file(): entries[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
            else: entries[relative] = "directory"
    files[name] = entries
schema = repr([(table, inspector.get_columns(table), inspector.get_foreign_keys(table), inspector.get_indexes(table)) for table in inspector.get_table_names()])
print(json.dumps({"records": records, "users": users, "files": files, "roots": roots, "schema": hashlib.sha256(schema.encode()).hexdigest(), "versions": versions, "timing": [settings.DEVELOP_TURN_TIMEOUT_SECONDS, settings.DEVELOP_TURN_PRESENCE_GRACE_SECONDS], "default_limit": settings.DEVELOP_USER_CONCURRENT_TURN_LIMIT_DEFAULT}, sort_keys=True))
`;

async function until(check, message, timeout = 15_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await check()) return;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error(message);
}

class AcceptanceResetPage {
  constructor(world) { this.world = world; this.sentinels = []; this.children = []; }
  get api() { return this.world.apiClient; }
  async snapshot() { return JSON.parse(await lifecycle.backendPythonOutput(snapshotScript)); }
  async sessionId(chatId) {
    return JSON.parse(await lifecycle.backendPythonOutput(`
import json, sys, uuid
from sqlmodel import Session
from app.core.db import engine
from app.models import DevelopmentChat
with Session(engine) as session:
    print(json.dumps(session.get(DevelopmentChat, uuid.UUID(sys.argv[1])).agent_session_id))
`, chatId));
  }
  async remember() {
    this.before = await this.snapshot();
    this.identity = await lifecycle.verifyStack();
    this.controlBefore = await lifecycle.controlState();
  }
  async seed() {
    this.user = await this.api.createUser();
    this.token = await this.api.authenticate(this.user.email, this.user.password);
    this.item = await this.api.createItem(this.user, 'reset fixture item');
    this.chat = await this.api.createDevelopmentChat(this.token, 'Reset fixture chat');
    const setup = await this.api.setupDevelopmentWorkspace(this.token, this.chat.id);
    assert.ok(setup.ok(), `Workspace fixture setup failed: ${setup.status()}`);
    await this.api.markWorkspace(this.chat.id, 'reset-fixture.txt');
    await this.api.seedDevelopmentMessages(this.chat.id, 2);
    await this.remember();
  }
  async seedWithUnrelated() { await this.seed(); await this.createSentinel(); this.beforeSentinels = await this.sentinelSnapshot(); }
  async createSentinel() {
    const project = `sdd-reset-sentinel-${randomUUID()}`;
    const network = `${project}-network`;
    const volume = `${project}-volume`;
    await lifecycle.dockerOutput(['network', 'create', '--internal', '--label', `sdd.preview.project=${project}`, '--label', `sdd.preview.chat-id=${randomUUID()}`, network]);
    this.sentinels.push({ kind: 'network', id: network });
    await lifecycle.dockerOutput(['volume', 'create', '--label', `sdd.preview.project=${project}`, volume]);
    this.sentinels.push({ kind: 'volume', id: volume });
  }
  async sentinelSnapshot() {
    return Promise.all(this.sentinels.map(({kind, id}) => lifecycle.dockerOutput([kind, 'inspect', id]).then(JSON.parse)));
  }
  async rejectCredentials() {
    const body = { run_id: lifecycle.state.projectName, reset_id: randomUUID(), expected_generation: this.controlBefore.generation };
    this.rejections = [];
    for (const token of ['', 'incorrect-reset-credential']) this.rejections.push(await lifecycle.controlRequest('reset', { method: 'POST', token, data: body }));
    const databaseToken = await this.api.authenticateSuperuser();
    this.rejections.push(await lifecycle.controlRequest('reset', { method: 'POST', token: databaseToken, data: body }));
  }
  async rejectOtherScope() {
    this.rejections = [];
    const body = { run_id: lifecycle.state.projectName, reset_id: randomUUID(), expected_generation: this.controlBefore.generation };
    this.rejections.push(await lifecycle.controlRequest('reset', { method: 'POST', run: 'another-run', data: { ...body, run_id: 'another-run' } }));
    for (const selection of [{ database: 'another_database' }, { root: '/another-root' }, { project: 'another-project' }]) {
      this.rejections.push(await lifecycle.controlRequest('reset', { method: 'POST', data: { ...body, ...selection } }));
    }
  }
  async expectRejectedUnchanged() {
    assert.ok(this.rejections.length);
    for (const response of this.rejections) assert.ok([401, 403, 409, 422].includes(response.status), `Reset scope/auth request unexpectedly returned ${response.status}`);
    assert.deepEqual(await this.snapshot(), this.before);
    const now = await lifecycle.controlState();
    assert.equal(now.generation, this.controlBefore.generation);
    await lifecycle.verifyStack();
  }
  async expectUsable() {
    const response = await this.api.developmentChat(this.token, this.chat.id);
    assert.ok(response.ok());
    await this.api.assertWorkspaceMarker(this.chat.id, 'reset-fixture.txt', true);
  }
  async expectBothUnchanged() { await this.expectRejectedUnchanged(); assert.deepEqual(await this.sentinelSnapshot(), this.beforeSentinels); }
  async reset() {
    this.previousContext = this.world.context;
    this.previousRequests = [...this.world.apiContexts];
    this.ack = await lifecycle.resetScenarioState();
    await this.world.replaceContexts();
  }
  async expectBaseline() {
    const baseline = await this.snapshot();
    for (const [table, state] of Object.entries(baseline.records)) assert.equal(state.count, table === 'user' ? 1 : 0, `Unexpected baseline records in ${table}`);
    assert.deepEqual(baseline.users, [{ email: lifecycle.state.env.FIRST_SUPERUSER, is_active: true, is_superuser: true, limit: baseline.default_limit }]);
    assert.deepEqual(baseline.files, { workspace: {}, agent: {} });
    assert.deepEqual(baseline.timing, [15, 0.3]);
    const live = await lifecycle.controlState();
    assert.equal(live.configuration, 'available');
    assert.deepEqual(live.timing, { timeout_seconds: 15, grace_seconds: 0.3 });
    assert.deepEqual(await this.api.fakeLlmRequests(), []);
    if (this.before) assert.deepEqual(baseline.roots, this.before.roots);
    this.baseline = baseline;
  }
  async expectAdministrator() {
    const token = await this.api.authenticateSuperuser();
    const user = await this.api.currentUser(token);
    assert.equal(user.is_active, true);
    assert.equal(user.is_superuser, true);
    assert.equal(user.concurrent_agent_turn_limit, (await this.snapshot()).default_limit);
    const created = await this.api.createUser();
    assert.ok(created.id);
  }
  async expectSchema() {
    const current = await this.snapshot();
    assert.equal(current.schema, this.before.schema);
    assert.deepEqual(current.versions, this.before.versions);
  }
  async modifyAdministrator() {
    await lifecycle.runBackendPython(`
from sqlmodel import Session, select
from app.core.config import settings
from app.core.db import engine
from app.core.security import get_password_hash
from app.models import User
with Session(engine) as session:
    user = session.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).one()
    user.hashed_password = get_password_hash("changed-fixture-password")
    user.is_active = False
    user.is_superuser = False
    user.concurrent_agent_turn_limit = 1
    user.full_name = "changed fixture administrator"
    session.add(user)
    session.commit()
`);
  }
  async orphanCheckout() {
    await this.seed();
    await lifecycle.runBackendPython(`
import sys, uuid
from sqlmodel import Session
from app.core.db import engine
from app.models import DevelopmentChat, DevelopmentMessage
from sqlalchemy import delete
with Session(engine) as session:
    chat = uuid.UUID(sys.argv[1])
    session.exec(delete(DevelopmentMessage).where(DevelopmentMessage.chat_id == chat))
    session.exec(delete(DevelopmentChat).where(DevelopmentChat.id == chat))
    session.commit()
`, this.chat.id);
  }
  async cliConfiguration(chatId, seed = false) {
    return JSON.parse(await lifecycle.backendPythonOutput(`
import hashlib, json, os, subprocess, sys, uuid
from pathlib import Path
from app.core.config import settings
from app.services.develop_agent import minimal_agent_environment
chat = str(uuid.UUID(sys.argv[1]))
environment = minimal_agent_environment(os.environ, provider_key=settings.OPENAI_API_KEY.get_secret_value(),
                                      provider_base_url=str(settings.OPENAI_BASE_URL) if settings.OPENAI_BASE_URL else None)
assert all(isinstance(key, str) and isinstance(value, str) for key, value in environment.items())
workspace = settings.DEVELOP_WORKSPACE_ROOT / chat
assert workspace.is_dir() and not workspace.is_symlink()
def cli(*args):
    result = subprocess.run(['opencode', *args], cwd=workspace, env=environment,
                            capture_output=True, text=True, timeout=12)
    if result.returncode != 0:
        raise RuntimeError('Installed CLI configuration inspection failed')
    return result.stdout
def config():
    return json.loads(cli('debug', 'config'))
value = config()
# Only a digest of fixed effective settings crosses the diagnostic boundary.
# Neither configuration contents nor the credential-store output is published.
projection = {key: value.get(key) for key in ('username','model','provider','permission')}
result = {'fingerprint': hashlib.sha256(json.dumps(projection, sort_keys=True).encode()).hexdigest(),
          'prior_credential_present': 'acceptance-reset-credential' in cli('auth', 'list')}
if sys.argv[2] == 'seed':
    config_root = Path(environment['XDG_CONFIG_HOME']) / 'opencode'
    config_root.mkdir(parents=True, exist_ok=True)
    (config_root / 'opencode.json').write_text(json.dumps({'username':'acceptance-reset-configuration'}))
    data_root = Path(environment['XDG_DATA_HOME']) / 'opencode'
    data_root.mkdir(parents=True, exist_ok=True)
    auth = data_root / 'auth.json'
    existing = json.loads(auth.read_text()) if auth.exists() else {}
    existing['acceptance-reset-credential'] = {'type':'api','key':'scenario-owned-secret'}
    auth.write_text(json.dumps(existing))
    (Path(environment['TMPDIR']) / 'askpass-fixture').write_text('scenario-owned-secret')
    result['configuration_consumed'] = config().get('username') == 'acceptance-reset-configuration'
    result['credential_consumed'] = 'acceptance-reset-credential' in cli('auth', 'list')
print(json.dumps(result))
`, chatId, seed ? 'seed' : 'inspect'));
  }
  async persistRealSession() {
    // Use the installed CLI, not a synthetic session file or mocked CLI result.
    await this.api.configureFakeLlm([{ kind: 'text', text: 'Real reset session marker', delay_seconds: 3 }]);
    const token = await this.api.authenticateSuperuser();
    this.sessionChat = await this.api.createDevelopmentChat(token, 'Persist a reset session');
    const setup = await this.api.setupDevelopmentWorkspace(token, this.sessionChat.id);
    assert.ok(setup.ok());
    const pending = this.api.exploreDevelopmentChat(token, this.sessionChat.id, 'Respond with a reset session marker');
    pending.catch(() => {});
    // Observe the actual installed CLI while it is running, not just settings in
    // a new interpreter or a fabricated session file. Never serialize its other
    // environment variables, command arguments, or credentials.
    let processes;
    await until(async () => {
      processes = JSON.parse(await lifecycle.backendPythonOutput(`
import json, os, stat, time
from pathlib import Path
keys = ('HOME','XDG_DATA_HOME','XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_STATE_HOME','XDG_RUNTIME_DIR','TMPDIR')
result = {}
deadline = time.monotonic() + 2
while time.monotonic() < deadline:
    processes, roots = {}, set()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            parent = int(process.joinpath('stat').read_text().rsplit(')', 1)[1].split()[1])
            processes[int(process.name)] = (process, parent)
            if process.joinpath('comm').read_text().strip() == 'opencode' and str(process.joinpath('cwd').resolve()).startswith('/develop-workspaces/'):
                roots.add(int(process.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
    owned = set(roots)
    while True:
        children = {pid for pid, (_, parent) in processes.items() if parent in owned}
        if children.issubset(owned):
            break
        owned.update(children)
    for pid in owned:
        process = processes[pid][0]
        try:
            environment = dict(entry.split('=', 1) for entry in process.joinpath('environ').read_bytes().decode().split('\\0') if '=' in entry)
            entry = result.setdefault(pid, {'environment': {key: environment.get(key) for key in keys}, 'writable_files': []})
            for descriptor in process.joinpath('fd').iterdir():
                try:
                    if not stat.S_ISREG(descriptor.stat().st_mode):
                        continue
                    information = process.joinpath('fdinfo', descriptor.name).read_text().splitlines()
                    flags = int(next(line.split(':', 1)[1].strip() for line in information if line.startswith('flags:')), 8)
                    if flags & os.O_ACCMODE != os.O_RDONLY:
                        filename = os.readlink(descriptor)
                        if filename not in entry['writable_files']:
                            entry['writable_files'].append(filename)
                except (FileNotFoundError, ProcessLookupError):
                    continue
        except (FileNotFoundError, ProcessLookupError):
            continue
    time.sleep(0.05)
print(json.dumps(list(result.values())))
`));
      return processes.length > 0;
    }, 'Installed OpenCode storage environment could not be observed');
    const expected = { HOME: 'home', XDG_DATA_HOME: 'data', XDG_CONFIG_HOME: 'config',
      XDG_CACHE_HOME: 'cache', XDG_STATE_HOME: 'state', XDG_RUNTIME_DIR: 'runtime', TMPDIR: 'tmp' };
    for (const process of processes) {
      for (const [key, child] of Object.entries(expected)) assert.equal(process.environment[key], `/acceptance-agent-state/${child}`);
      for (const filename of process.writable_files) assert.ok(
        filename.startsWith('/acceptance-agent-state/') || filename.startsWith('/develop-workspaces/'),
        'Installed OpenCode has writable regular storage outside the owned reset roots');
    }
    const result = await pending;
    assert.ok(result.ok());
    await this.api.waitForDevelopmentMessage(token, this.sessionChat.id, 'Real reset session marker');
    await this.api.assertAgentSession(this.sessionChat.id);
    this.oldSession = await this.sessionId(this.sessionChat.id);
    this.trustedCli = await this.cliConfiguration(this.sessionChat.id, true);
    assert.equal(this.trustedCli.prior_credential_present, false);
    assert.equal(this.trustedCli.configuration_consumed, true, 'Installed CLI did not consume the prior effective configuration');
    assert.equal(this.trustedCli.credential_consumed, true, 'Installed CLI did not consume the prior credential store');
    const persisted = await this.snapshot();
    assert.ok(Object.keys(persisted.files.agent).some(name => name.includes('opencode')), 'Installed CLI did not persist state inside acceptance-owned storage');
    this.before = persisted;
  }
  async expectFilesGone() { await this.expectBaseline(); assert.ok(this.oldSession); }
  async expectStorageAvailable() {
    await lifecycle.verifyStack();
    const current = await this.snapshot();
    assert.deepEqual(current.roots, this.before.roots);
    const user = await this.api.createUser();
    const token = await this.api.authenticate(user.email, user.password);
    const chat = await this.api.createDevelopmentChat(token, 'New workspace after reset');
    assert.ok((await this.api.setupDevelopmentWorkspace(token, chat.id)).ok());
    this.nextSessionChat = { chat, token };
  }
  async expectNewSession() {
    const { chat, token } = this.nextSessionChat;
    const baseline = await this.cliConfiguration(chat.id);
    assert.equal(baseline.fingerprint, this.trustedCli.fingerprint, 'Installed CLI did not restore the trusted effective configuration');
    assert.equal(baseline.prior_credential_present, false, 'Installed CLI inherited a prior consumed credential');
    await this.api.configureFakeLlm([{ kind: 'text', text: 'Independent reset session' }]);
    assert.ok((await this.api.exploreDevelopmentChat(token, chat.id, 'Start an independent session')).ok());
    await this.api.waitForDevelopmentMessage(token, chat.id, 'Independent reset session');
    const session = await this.sessionId(chat.id);
    assert.ok(session);
    assert.notEqual(session, this.oldSession);
    const now = await this.snapshot();
    assert.ok(!Object.keys(now.files.agent).some(name => name.includes('previous-credential') || name.includes('askpass-fixture')));
  }
  async contaminateAll() {
    await this.seed();
    await this.api.configureFakeLlm([{ kind: 'text', text: 'must not reach next scenario' }]);
    await this.api.configureTurnLifecycle({ timeoutSeconds: 3, graceSeconds: 2 });
    await lifecycle.configureDemoRepository(false);
  }
  async expectAcknowledgement() {
    assert.equal(this.ack.run_id, lifecycle.state.projectName);
    assert.equal(this.ack.generation, this.controlBefore.generation + 1);
    assert.equal(this.ack.baseline_verified, true);
    assert.equal(this.ack.phase, 'ready');
    assert.ok(!JSON.stringify(this.ack).includes(lifecycle.state.resetToken));
    assert.ok(!JSON.stringify(this.ack).includes(lifecycle.state.env.DEMO_GITHUB_TOKEN));
  }
  async expectRealBaseline() {
    await this.expectBaseline();
    await this.api.authenticateSuperuser();
    assert.deepEqual((await this.api.listItems()), []);
    assert.deepEqual((await this.api.listDevelopmentChats(this.api.superuserToken)).data, []);
    const response = await this.world.page.request.post('/api/v1/testing/llm/v1/responses', { data: { input: [] } });
    assert.equal(response.status(), 500, 'Prior fake reply survived verified reset');
  }
  async expectFreshContexts() {
    assert.notEqual(this.world.context, this.previousContext);
    assert.equal(this.world.page.context(), this.world.context);
    assert.ok(this.previousContext.pages().length === 0);
    for (const api of this.previousRequests) await assert.rejects(api.get('/api/v1/utils/health-check/'));
    await lifecycle.verifyStack();
  }
  async completedLostResponse() {
    this.identity = await lifecycle.verifyStack();
    const current = await lifecycle.controlState();
    this.retry = { run_id: current.run_id, reset_id: randomUUID(), expected_generation: current.generation };
    const completed = await lifecycle.controlRequest('reset', { method: 'POST', data: this.retry });
    assert.ok(completed.ok);
    this.completed = completed.body;
    // Deliberately do not publish this ACK to application contexts or start scenario work.
    this.before = await this.snapshot();
  }
  async retryReset() { this.retried = await lifecycle.controlRequest('reset', { method: 'POST', data: this.retry }); }
  async expectRetrySafe() {
    assert.ok(this.retried.ok);
    assert.deepEqual(this.retried.body, this.completed);
    assert.deepEqual(await this.snapshot(), this.before);
    await lifecycle.verifyStack();
  }
  async nextScenarioState() {
    await this.completedLostResponse();
    await this.world.replaceContexts();
    await this.seed();
    // Join a first real turn so CLI/plugin bootstrap writes complete during
    // fixture creation, rather than racing the preservation snapshot. The next
    // delayed real turn uses that persisted session and stays active at retry.
    await this.api.configureFakeLlm([{ kind: 'text', text: 'New-generation session prepared' }]);
    assert.ok((await this.api.exploreDevelopmentChat(this.token, this.chat.id, 'Prepare the new-generation session')).ok());
    await this.api.waitForDevelopmentMessage(this.token, this.chat.id, 'New-generation session prepared');
    await this.api.configureFakeLlm([{ kind: 'text', text: 'New work survived stale reset', delay_seconds: 10 }]);
    this.newWorkFinished = false;
    this.pendingNewWork = this.api.exploreDevelopmentChat(this.token, this.chat.id, 'Keep this new-generation work alive')
      .finally(() => { this.newWorkFinished = true; });
    this.pendingNewWork.catch(() => {});
    await until(async () => (await this.api.fakeLlmRequests()).length > 0, 'New-generation work never reached the real provider');
    const state = await lifecycle.controlState();
    assert.ok(Object.values(state.active_work).some(count => count > 0));
    this.newWorkGeneration = state.generation;
    this.nextState = await this.snapshot();
  }
  async expectStaleRejected() { assert.equal(this.retried.status, 409); }
  async expectNewStatePreserved() {
    const current = await lifecycle.controlState();
    assert.equal(current.generation, this.newWorkGeneration);
    assert.ok(Object.values(current.active_work).some(count => count > 0), 'Stale retry drained active new work');
    assert.equal(this.newWorkFinished, false, 'Stale retry cancelled or completed the delayed new work');
    assert.deepEqual(await this.snapshot(), this.nextState);
    await this.expectUsable();
    assert.ok((await this.pendingNewWork).ok(), 'Stale retry cancelled the real new-generation operation');
    await this.api.waitForDevelopmentMessage(this.token, this.chat.id, 'New work survived stale reset');
    await lifecycle.verifyStack();
  }
  async armNextBoundaryFailure() {
    const manifest = JSON.parse(fs.readFileSync(process.env.ACCEPTANCE_MANIFEST_PATH, 'utf8'));
    const root = fs.realpathSync(manifest.specRoot);
    assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
    assert.ok(path.basename(root).startsWith('sdd-gate-fixture-'), 'Faults require an owned isolated command fixture');
    assert.ok(manifest.entries.some(entry => entry.steps.includes('the isolated command fixture arms a bounded filesystem cleanup fault')));
    const { createFilesystemCleanupFault } = require('../acceptance-cleanup-fixtures.cjs');
    this.cleanupFault = await createFilesystemCleanupFault();
    lifecycle.record('command-boundary-fixture', { generation: lifecycle.state.generation });
  }
  async configuredRepository() {
    await lifecycle.configureDemoRepository(true);
    await this.remember();
    this.initialBackend = await lifecycle.backendInfo();
    assert.equal(this.initialBackend.healthy, true);
  }
  async sameRepositoryRequests() {
    await lifecycle.configureDemoRepository(true);
    await this.api.configureFakeLlm([{ kind: 'text', text: 'previous configuration scenario reply' }]);
    await this.reset();
    await lifecycle.configureDemoRepository(true);
  }
  async expectNoRecreation() { await this.expectSameStack(); assert.equal(lifecycle.state.backendRecreations, 0); }
  async expectIndependentState() {
    await this.expectFreshContexts();
    assert.deepEqual(await this.api.fakeLlmRequests(), []);
    const api = await this.world.openApiContext();
    assert.equal((await api.post('/api/v1/testing/llm/v1/responses', { data: { input: [] } })).status(), 500);
  }
  async unavailableRepository() { await lifecycle.configureDemoRepository(false); }
  async expectUnavailableRepository() {
    const info = await lifecycle.backendInfo();
    assert.equal(info.repo, '');
    assert.equal(info.healthy, true);
    assert.equal(info.id, this.initialBackend.id);
    await lifecycle.verifyStack();
  }
  async availableRepository() { await lifecycle.configureDemoRepository(true); }
  async expectAvailableRepository() { await this.expectConfigurationBaseline(); }
  async anotherRepositoryRequest() { await lifecycle.configureDemoRepository(true); await this.expectNoRecreation(); }
  async configurationRoundTrip() {
    await lifecycle.configureDemoRepository(false);
    assert.deepEqual(await this.snapshot(), this.before);
    await lifecycle.configureDemoRepository(true);
    assert.deepEqual(await this.snapshot(), this.before);
  }
  async expectFixturesPreserved() { await this.expectUsable(); assert.deepEqual(await this.snapshot(), this.before); }
  async leaveUnavailable() { await lifecycle.configureDemoRepository(false); }
  async expectConfigurationBaseline() { assert.equal((await lifecycle.backendInfo()).repo, 'https://example.com/acceptance/demo-repository.git'); await lifecycle.verifyStack(); }
  async recordIdentity() { await this.remember(); }
  async consecutiveResets() {
    this.startGeneration = lifecycle.state.generation;
    await this.seed();
    await this.reset();
    await this.expectBaseline();
    await this.seed();
    await this.reset();
    await this.expectBaseline();
  }
  async expectSameStack() { assert.deepEqual(await lifecycle.verifyStack(), this.identity); }
  async expectOneStack() { assert.equal(lifecycle.state.events.filter(event => event.type === 'stack-start').length, 1); }
  async expectSerial() {
    let active;
    for (const event of lifecycle.state.events) {
      if (event.type === 'scenario-start') { assert.equal(active, undefined); active = event.scenario; }
      if (event.type === 'scenario-end') { assert.equal(event.scenario, active); active = undefined; }
    }
    assert.equal(active, this.world.scenarioName);
  }
  async createUntrackedPreviews() {
    await this.seed();
    // Exercise the real controller routing registry, but deliberately leave page tracking empty.
    await this.world.previewWorkloadPage.start(this.chat.id);
    this.world.previewWorkloadPage.chatIds = [];
    const orphan = randomUUID();
    const prefix = `${lifecycle.state.projectName}-preview-${orphan}`;
    const labelArgs = ['--label', `sdd.preview.project=${lifecycle.state.projectName}`, '--label', `sdd.preview.chat-id=${orphan}`];
    await lifecycle.dockerOutput(['network', 'create', '--internal', ...labelArgs, `${prefix}-network`]);
    await lifecycle.dockerOutput(['volume', 'create', ...labelArgs, `${prefix}-socket`]);
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'sdd-reset-image-'));
    try {
      fs.writeFileSync(path.join(directory, 'Dockerfile'), 'FROM scratch\nCMD ["fixture"]\n');
      await lifecycle.dockerOutput(['build', ...labelArgs, '-t', `${prefix}-fixture:latest`, directory], { timeout: 120_000 });
    } finally { fs.rmSync(directory, { recursive: true, force: true }); }
    await lifecycle.dockerOutput(['create', ...labelArgs, '--name', `${prefix}-helper`, '--network', `${prefix}-network`, '--mount', `type=volume,source=${prefix}-socket,target=/socket`, `${prefix}-fixture:latest`]);
    this.previewBefore = await lifecycle.ownedResources();
    for (const kind of ['containers', 'networks', 'volumes', 'images']) assert.ok(this.previewBefore[kind].length, `Missing ${kind} orphan fixture`);
    await this.remember();
  }
  async expectPreviewGone() {
    const resources = await lifecycle.ownedResources();
    assert.deepEqual(resources.containers, []);
    assert.deepEqual(resources.volumes, []);
    assert.deepEqual(resources.images, []);
    // Only the controller's explicitly immutable project-shared egress network may remain.
    for (const id of resources.networks) {
      const [network] = JSON.parse(await lifecycle.dockerOutput(['network', 'inspect', id]));
      assert.equal(network.Labels?.['sdd.preview.chat-id'], undefined);
      assert.equal(Object.keys(network.Containers || {}).length, 0);
    }
    await this.expectBaseline();
  }
  async unrelatedPreviews() { await this.createSentinel(); this.beforeSentinels = await this.sentinelSnapshot(); }
  async expectSentinelsUnchanged() { assert.deepEqual(await this.sentinelSnapshot(), this.beforeSentinels); }
  async activeWork() {
    await this.seed();
    await this.api.configureTurnLifecycle({ timeoutSeconds: 15, graceSeconds: 5 });
    await this.api.configureFakeLlm([{ kind: 'delay', text: 'Old reply must not persist', delay_seconds: 10 }]);
    this.pendingTurn = this.api.exploreDevelopmentChat(this.token, this.chat.id, 'Start work before reset').then(response => response.status()).catch(() => 0);
    await until(async () => (await this.api.fakeLlmRequests()).length > 0, 'Prior Agent Turn did not reach the actual provider');
    await this.api.waitForAgentTurn(this.token, this.chat.id);
    await this.world.previewWorkloadPage.start(this.chat.id);
    this.world.previewWorkloadPage.chatIds = [];
    this.before = await this.snapshot();
  }
  async expectJoined() {
    await this.pendingTurn;
    assert.deepEqual((await lifecycle.controlState()).active_work, {});
    await this.expectPreviewGone();
  }
  async expectNoLateWork() {
    const baseline = await this.snapshot();
    await new Promise(resolve => setTimeout(resolve, 250));
    assert.deepEqual(await this.snapshot(), baseline);
    assert.deepEqual(await this.api.fakeLlmRequests(), []);
  }
  async expectNewTurnCapacity() {
    const token = await this.api.authenticateSuperuser();
    const chat = await this.api.createDevelopmentChat(token, 'New turn after drain');
    assert.ok((await this.api.setupDevelopmentWorkspace(token, chat.id)).ok());
    await this.api.configureFakeLlm([{ kind: 'text', text: 'New scenario reply' }]);
    assert.ok((await this.api.exploreDevelopmentChat(token, chat.id, 'A new independent turn')).ok());
    await this.api.waitForDevelopmentMessage(token, chat.id, 'New scenario reply');
    assert.ok((await this.api.currentUser(token)).concurrent_agent_turn_limit >= 1);
  }
  async resetInProgress() {
    await this.seed();
    const admin = await this.api.authenticateSuperuser();
    const user = await this.api.currentUser(admin);
    const script = `
import sys, time
from sqlalchemy import text
from app.core.db import engine
with engine.begin() as connection:
    connection.execute(text('SELECT id FROM "user" WHERE id = :id FOR UPDATE'), {"id": sys.argv[1]})
    print("LOCK_READY", flush=True)
    time.sleep(8)
`;
    const child = spawn('docker', lifecycle.composeArgs(lifecycle.state.projectName, 'exec', '--no-TTY', 'backend', 'python', '-c', script, user.id), { env: lifecycle.state.env, stdio: ['ignore', 'pipe', 'pipe'] });
    this.children.push(child);
    await new Promise((resolve, reject) => {
      let output = '';
      child.stdout.on('data', chunk => { output += chunk; if (output.includes('LOCK_READY')) resolve(); });
      child.once('error', reject);
      child.once('exit', code => { if (!output.includes('LOCK_READY')) reject(new Error(`Database lock fixture exited ${code}`)); });
    });
    this.blockedMutation = fetch(`${lifecycle.state.baseUrl}/api/v1/users/me`, { method: 'PATCH', headers: { Authorization: `Bearer ${admin}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ full_name: 'Blocked admission fixture' }), signal: AbortSignal.timeout(20_000) }).then(response => response.status()).catch(() => 0);
    await until(async () => JSON.parse(await lifecycle.backendPythonOutput(`
import json
from sqlalchemy import text
from app.core.db import engine
with engine.connect() as connection:
    count = connection.execute(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND query LIKE '%UPDATE%user%'")).scalar_one()
print(json.dumps(count > 0))
`)), 'Mutating HTTP fixture did not block on a real database lock');
    this.resetPending = this.reset();
    this.resetPending.catch(() => {});
    await until(async () => (await lifecycle.controlState()).phase === 'quiescing', 'Reset did not close admissions while old work was active');
  }
  async attemptMutatingRequests() {
    this.admissionResponses = [];
    for (const suffix of ['messages/explore', 'workspace/setup', 'preview/start']) {
      const response = await fetch(`${lifecycle.state.baseUrl}/api/v1/develop/chats/${this.chat.id}/${suffix}`, { method: 'POST', headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ content: 'Must not be admitted' }), signal: AbortSignal.timeout(5_000) });
      this.admissionResponses.push(response.status);
    }
  }
  async expectAdmissionClosed() {
    assert.deepEqual(this.admissionResponses, [503, 503, 503]);
    await this.blockedMutation;
    await this.resetPending;
  }
  async expectNoPartialState() { await this.expectBaseline(); }
  async dispose() {
    await Promise.allSettled([this.pendingTurn, this.pendingNewWork, this.blockedMutation, this.resetPending].filter(Boolean));
    for (const child of this.children) {
      if (child.exitCode === null) await new Promise(resolve => child.once('exit', resolve));
    }
    for (const {kind, id} of this.sentinels.reverse()) await lifecycle.dockerOutput([kind, 'rm', id]);
    this.sentinels = [];
  }
}
module.exports = { AcceptanceResetPage, snapshotScript, until };
