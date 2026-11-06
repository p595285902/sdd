'use strict';

// One real invocation per process. Only IPC carries private run credentials;
// stdout, lifecycle events and final results must remain credential-free.
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const lifecycle = require('../support/app-lifecycle.js');
const { state, record, startApplication, stopApplication, resetScenarioState,
  controlRequest, controlState, dockerOutput, backendPythonOutput } = lifecycle;
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const kinds = new Set(['completed', 'failure', 'cancellation', 'outside', 'deadline', 'cleanup', 'filesystem', 'partial-controller']);
const { createFilesystemCleanupFault, inspectFilesystemCleanupFault, repairFilesystemCleanupFault } = require('../../support/acceptance-cleanup-fixtures.cjs');
let filesystemFault;
let volumeBlocker;
let kind;
let terminal;
let operation = Promise.resolve();
let cancellation;
let fixture;
let lock;
let diagnostics = {};

function send(message) {
  return new Promise((resolve, reject) => {
    if (!process.connected) return reject(new Error('Lifecycle parent IPC disconnected'));
    process.send(message, error => error ? reject(error) : resolve());
  });
}

async function eventually(probe, description, timeout = 15_000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (await probe()) return;
    await delay(50);
  }
  throw new Error(`Lifecycle fixture did not establish ${description}`);
}

async function previewFixture(ambiguous = false) {
  const chat = randomUUID();
  const name = `${state.projectName}-preview-${chat}-lifecycle`;
  const labels = ['--label', `sdd.preview.project=${state.projectName}`];
  if (!ambiguous) labels.push('--label', `sdd.preview.chat-id=${chat}`);
  const network = (await dockerOutput(['network', 'create', '--internal', ...labels, name])).trim();
  fixture = { network }; // Register ownership immediately, even if later setup fails.
  if (!ambiguous) {
    const volume = (await dockerOutput(['volume', 'create', ...labels, `${name}-data`])).trim();
    fixture.volume = volume;
    fixture.container = (await dockerOutput(['create', ...labels, '--name', `${name}-workload`,
      '--network', network, '--mount', `type=volume,source=${volume},target=/var/lib/postgresql`, 'postgres:18'])).trim();
  }
  fixture.before = JSON.parse(await dockerOutput(['network', 'inspect', network]));
  record('lifecycle-preview-fixture', { ambiguous, network });
}

const databaseSnapshotCode = `
import json
from sqlalchemy import text
from app.core.db import engine
with engine.connect() as connection:
    tables = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
    rows = {}
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        rows[table] = connection.execute(text('SELECT to_jsonb(t)::text FROM ' + quoted + ' AS t ORDER BY to_jsonb(t)::text')).scalars().all()
    print(json.dumps(rows, sort_keys=True))
`;

async function outsideFixture() {
  // Real data plus a file in the application's mounted workspace, not an endpoint fault.
  await backendPythonOutput(`
from pathlib import Path
from sqlmodel import Session
from app.core.db import engine
from app.models import User
from app.core.security import get_password_hash
with Session(engine) as session:
    session.add(User(email='lifecycle-outside@example.com', hashed_password=get_password_hash('lifecycle-password'), full_name='must remain'))
    session.commit()
Path('/develop-workspaces/lifecycle-outside-sentinel').write_text('must remain')
`);
  await previewFixture();
  diagnostics.databaseBefore = JSON.parse(await backendPythonOutput(databaseSnapshotCode));
  diagnostics.resourcesBefore = await lifecycle.ownedResources();
}

async function login() {
  const response = await fetch(`${state.baseUrl}/api/v1/login/access-token`, {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: 'admin@example.com', password: 'acceptance-admin-password' }),
    signal: AbortSignal.timeout(10_000),
  });
  assert.equal(response.status, 200, 'Lifecycle fixture administrator cannot authenticate');
  return (await response.json()).access_token;
}

async function deadlineFixture() {
  const accessToken = await login();
  const identifier = randomUUID();
  const ready = `/tmp/lifecycle-lock-${identifier}-ready`;
  const release = `/tmp/lifecycle-lock-${identifier}-release`;
  const code = `
import sys, time
from pathlib import Path
from sqlalchemy import text
from app.core.db import engine
ready, release = map(Path, sys.argv[1:])
try:
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text('SELECT id FROM "user" WHERE email=:email FOR UPDATE'), {'email':'admin@example.com'}).all()
        ready.write_text('locked')
        deadline = time.monotonic() + 45
        while not release.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        transaction.rollback()
finally:
    ready.unlink(missing_ok=True)
    release.unlink(missing_ok=True)
`;
  const output = backendPythonOutput(code, ready, release);
  // A separate docker-exec/Python process owns a bounded PostgreSQL transaction.
  // Observe its outcome without allowing a rejection to become unhandled.
  lock = { ready, release, output: output.then(() => ({ ok: true }), () => ({ ok: false })) };
  await eventually(async () => (await backendPythonOutput(`
import sys
from pathlib import Path
print('ready' if Path(sys.argv[1]).exists() else 'waiting')
`, ready)).trim() === 'ready', 'row lock');
  const abort = new AbortController();
  lock.request = fetch(`${state.baseUrl}/api/v1/users/me`, {
    method: 'PATCH', headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ full_name: 'lifecycle blocked mutation' }), signal: abort.signal,
  }).then(response => ({ status: response.status }), () => ({ cancelled: true }));
  await eventually(async () => (await backendPythonOutput(`
from sqlalchemy import text
from app.core.db import engine
with engine.connect() as connection:
    print(connection.execute(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query ILIKE :query"), {'query':'%UPDATE%user%'}).scalar())
`)).trim() !== '0', 'real HTTP mutation blocked on PostgreSQL');
  abort.abort();
  await lock.request;
  await eventually(async () => (await backendPythonOutput(`
from sqlalchemy import text
from app.core.db import engine
with engine.connect() as connection:
    print(connection.execute(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query ILIKE :query"), {'query':'%UPDATE%user%'}).scalar())
`)).trim() !== '0', 'PostgreSQL mutation remaining blocked after socket cancellation');
  await eventually(async () => Object.values((await controlState()).active_work).some(count => count > 0),
    'admitted HTTP work surviving socket cancellation');
  diagnostics.blockedWork = (await controlState()).active_work;
  record('lifecycle-lock-established', { socketCancelled: true, activeWork: diagnostics.blockedWork });
}

async function releaseLock() {
  if (!lock) return;
  await backendPythonOutput(`
import sys
from pathlib import Path
Path(sys.argv[1]).write_text('release')
`, lock.release);
  assert.equal((await lock.output).ok, true, 'Bounded row-lock fixture failed to finish');
  lock = undefined;
  record('lifecycle-lock-released');
}

async function partialControllerFixture() {
  await previewFixture();
  // This independently owned blocker is deliberately outside controller preview
  // discovery. Engine refuses deletion of its mounted volume AFTER the actual
  // preview workload/network have been deleted. No Engine mock or API fault.
  volumeBlocker = (await dockerOutput(['create', '--label', `sdd.acceptance.fixture=${state.projectName}`,
    '--mount', `type=volume,source=${fixture.volume},target=/var/lib/postgresql`, 'postgres:18'])).trim();
}

async function releaseCleanupFaults() {
  if (filesystemFault) {
    await repairFilesystemCleanupFault(filesystemFault);
    filesystemFault = undefined;
  }
  if (volumeBlocker) {
    const info = JSON.parse(await dockerOutput(['inspect', volumeBlocker]))[0];
    assert.equal(info.Config.Labels['sdd.acceptance.fixture'], state.projectName);
    assert.ok(info.Mounts.some(mount => mount.Name === fixture.volume));
    await dockerOutput(['rm', '-f', volumeBlocker]);
    volumeBlocker = undefined;
  }
}

async function beginScenario(name) {
  await resetScenarioState(); // The boundary must succeed before the runner admits a scenario.
  record('scenario-start', { name });
}

async function start(requestedKind) {
  assert.ok(kinds.has(requestedKind), 'Unsupported lifecycle fixture');
  assert.equal(kind, undefined, 'One child may own only one invocation');
  kind = requestedKind;
  try {
    await startApplication({ acceptanceMode: kind !== 'outside', resetTimeoutSeconds: kind === 'deadline' ? 1 : 60 });
  } finally {
    if (state.resetToken) await send({ type: 'private-credential', credential: state.resetToken });
  }
  if (kind === 'deadline') {
    // Prestart already created the canonical database. Do not spend the special
    // one-second failure deadline on an unrelated initial warm-up reset.
    record('scenario-start', { name: 'fixture' });
  } else if (kind !== 'outside') await beginScenario('fixture');
  if (kind === 'failure' || kind === 'cancellation') await previewFixture();
  if (kind === 'cleanup') await previewFixture(true);
  if (kind === 'filesystem') {
    await previewFixture();
    filesystemFault = await createFilesystemCleanupFault();
  }
  if (kind === 'partial-controller') await partialControllerFixture();
  if (kind === 'outside') await outsideFixture();
  if (kind === 'deadline') await deadlineFixture();
  return { project: state.projectName, kind };
}

async function outsideControls() {
  const responses = [];
  for (const [endpoint, method, data] of [
    ['state', 'GET'],
    ['reset', 'POST', { run_id: state.projectName, reset_id: randomUUID(), expected_generation: 0 }],
    ['configuration', 'PATCH', { run_id: state.projectName, expected_generation: 0, mode: 'unavailable' }],
  ]) {
    const response = await controlRequest(endpoint, { method, data });
    assert.equal(response.status, 404, 'Acceptance backend control exists outside acceptance mode');
    responses.push({ endpoint, status: response.status });
  }
  // The destructive internal controller boundary must also be absent, not just
  // the browser-facing routes. Credentials stay within this backend process.
  const controller = JSON.parse(await backendPythonOutput(`
import json
import httpx
from app.core.config import settings
headers = {'Authorization': 'Bearer ' + settings.ACCEPTANCE_RESET_TOKEN.get_secret_value(), 'X-Acceptance-Run': settings.ACCEPTANCE_RUN_ID}
with httpx.Client(timeout=10) as client:
    statuses = []
    for action in ('state', 'quiesce', 'reset', 'resume'):
        result = client.request('GET' if action == 'state' else 'POST', 'http://preview-controller:8090/testing/acceptance/' + action, headers=headers, **({} if action == 'state' else {'json':{'run_id':settings.ACCEPTANCE_RUN_ID,'reset_id':'outside-fixture','expected_generation':0}}))
        statuses.append({'action':action,'status':result.status_code})
print(json.dumps(statuses))
`));
  for (const response of controller) assert.equal(response.status, 404, 'Controller bulk acceptance control exists outside acceptance mode');
  assert.deepEqual(JSON.parse(await backendPythonOutput(databaseSnapshotCode)), diagnostics.databaseBefore);
  assert.equal((await backendPythonOutput(`
from pathlib import Path
print(Path('/develop-workspaces/lifecycle-outside-sentinel').read_text())
`)).trim(), 'must remain');
  assert.deepEqual(await lifecycle.ownedResources(), diagnostics.resourcesBefore);
  assert.deepEqual(JSON.parse(await dockerOutput(['network', 'inspect', fixture.network])), fixture.before);
  return { responses, controller, unchanged: true };
}

async function failedReset() {
  let release;
  if (lock) {
    // Release only after several seconds: well beyond the real one-second reset
    // deadline, but bounded independently so a broken reset cannot strand SQL.
    release = delay(4_000).then(releaseLock);
    release.catch(() => {});
  }
  try {
    let failed = false;
    try { await resetScenarioState(); } catch { failed = true; }
    assert.equal(failed, true, 'Terminal reset fixture unexpectedly acknowledged a baseline');
    const status = await controlState();
    diagnostics.reset = status;
    assert.equal(status.phase, 'failed');
    assert.equal(status.baseline_verified, false);
    const expectedPhase = kind === 'deadline' ? 'quiescing' : kind === 'filesystem' ? 'cleaning_files' : 'cleaning_previews';
    assert.equal(status.failure_phase, expectedPhase);
    assert.equal(status.generation, state.generation, 'Failed cleanup published a new generation');
    if (kind === 'cleanup') {
      diagnostics.refusedFixtureUnchanged = JSON.parse(await dockerOutput(['network', 'inspect', fixture.network]));
      assert.deepEqual(diagnostics.refusedFixtureUnchanged, fixture.before, 'Ambiguous preview resource was deleted or mutated before refusal');
    } else if (kind === 'filesystem' || kind === 'partial-controller') {
      const resources = await lifecycle.ownedResources();
      assert.ok(!resources.networks.includes(fixture.network));
      assert.ok(!resources.containers.includes(fixture.container));
      if (kind === 'filesystem') {
        diagnostics.partialCleanup = await inspectFilesystemCleanupFault(filesystemFault);
        assert.deepEqual(diagnostics.partialCleanup, { workspace_removed: true, agent_remains: true });
      } else {
        assert.ok(resources.volumes.includes(fixture.volume), 'Engine did not retain the blocked volume');
        diagnostics.partialCleanup = { workload_removed: true, network_removed: true, volume_remains: true };
      }
    }
    let blocked = false;
    try { await beginScenario('later'); } catch { blocked = true; }
    assert.equal(blocked, true, 'A later scenario entered after a failed reset');
    record('scenario-blocked', { name: 'later', phase: status.failure_phase });
    const admission = await fetch(`${state.baseUrl}/api/v1/users/signup`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'must-not-enter@example.com', password: 'lifecycle-password' }),
      signal: AbortSignal.timeout(5_000),
    });
    assert.equal(admission.status, 503, 'Application mutation admission reopened after failed reset');
    diagnostics.admissionStatus = admission.status;
    record('invocation-failed', { phase: status.failure_phase });
  } finally {
    if (release) await release;
  }
}

async function finish(outcome, exitCode) {
  if (terminal) return terminal;
  terminal = (async () => {
    let cleanupError;
    try { await releaseLock(); await releaseCleanupFaults(); }
    catch { cleanupError = 'Bounded lifecycle fault cleanup failed'; }
    // Log capture must never prevent final cleanup. All captured streams pass
    // through the common lifecycle redactor and the parent's independent audit.
    if (!state.stopped) {
      try { await lifecycle.showApplicationLogs(); } catch { diagnostics.logsUnavailable = true; }
    }
    try { await stopApplication(); } catch { cleanupError = 'Owned lifecycle final teardown failed'; }
    const result = { outcome, project: state.projectName, kind,
      diagnostics, events: state.events, cleanupVerified: state.stopped && !cleanupError,
      ...(cleanupError ? { error: cleanupError } : {}) };
    await send({ type: 'result', result });
    process.exitCode = cleanupError ? 1 : exitCode;
    if (process.connected) process.disconnect();
    return result;
  })();
  return terminal;
}

async function execute() {
  if (kind === 'outside') {
    diagnostics.controls = await outsideControls();
    await finish('completed', 0);
  } else if (['deadline', 'cleanup', 'filesystem', 'partial-controller'].includes(kind)) {
    await failedReset();
    await finish('reset-failed', 1);
  } else if (kind === 'failure') {
    // A genuine failed scenario assertion drives the invocation's nonzero exit;
    // the terminal result is not merely a fabricated failure-shaped response.
    try {
      assert.fail('Intentional isolated lifecycle scenario failure');
    } catch {
      record('invocation-failed', { phase: 'scenario-execution' });
      await finish('failed', 1);
    }
  } else {
    record('invocation-completed');
    await finish('completed', 0);
  }
}

if (require.main === module) {
  // No parent event-log file is inherited: results are audited then published by
  // the lifecycle page, rather than child writes bypassing credential checking.
  delete process.env.ACCEPTANCE_EVENT_LOG;
  process.on('message', message => {
    operation = operation.then(async () => {
      if (terminal) return;
      try {
        if (message.command === 'start') {
          const ready = await start(message.kind);
          await send({ type: 'ready', id: message.id, ready });
        } else if (message.command === 'execute') {
          await execute();
        } else if (message.command === 'stop') {
          await finish('aborted', 1);
        } else {
          throw new Error('Unsupported lifecycle command');
        }
      } catch (error) {
        record('lifecycle-fixture-error', { phase: diagnostics.reset?.failure_phase || kind || 'startup',
          reason: lifecycle.redact(error.message || 'Lifecycle fixture failed') });
        await finish('fixture-error', 1);
      }
    }).catch(() => { process.exitCode = 1; if (process.connected) process.disconnect(); });
  });
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
    if (cancellation || terminal) return;
    cancellation = signal;
    operation = operation.then(async () => {
      record('invocation-cancelled', { signal });
      await finish('cancelled', signal === 'SIGINT' ? 130 : 143);
    });
  });
  process.on('disconnect', () => {
    if (terminal) return;
    operation = operation.then(async () => {
      try { await releaseLock(); await releaseCleanupFaults(); await stopApplication(); }
      finally { process.exitCode = 1; }
    });
  });
}

module.exports = { kinds, databaseSnapshotCode };
