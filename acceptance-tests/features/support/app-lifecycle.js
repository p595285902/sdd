'use strict';

const { execFile, spawn } = require('node:child_process');
const { randomBytes, randomUUID } = require('node:crypto');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '../../..');
const composeFiles = [path.join(repoRoot, 'compose.yml'), path.join(repoRoot, 'acceptance-tests/compose.yml')];
const demoRepository = 'https://example.com/acceptance/demo-repository.git';
const demoToken = 'acceptance-token';
const state = {
  baseUrl: undefined, browserBaseUrl: undefined, projectName: undefined,
  demoRepositoryAvailable: undefined,
  generation: 0, fatal: undefined, events: [], stopped: true,
};

function record(type, details = {}) {
  const event = { type, at: Date.now(), project: state.projectName, ...details };
  state.events.push(event);
  if (process.env.ACCEPTANCE_EVENT_LOG) fs.appendFileSync(process.env.ACCEPTANCE_EVENT_LOG, `${JSON.stringify(event)}\n`);
  console.log(`[acceptance-stack] ${JSON.stringify(event)}`);
  return event;
}

function redact(value) {
  let text = String(value);
  for (const secret of [state.resetToken, state.env?.DEMO_GITHUB_TOKEN, state.env?.SECRET_KEY,
    state.env?.FIRST_SUPERUSER_PASSWORD, state.env?.POSTGRES_PASSWORD, state.env?.OPENAI_API_KEY]) {
    if (secret) text = text.split(secret).join('[redacted]');
  }
  return text;
}

function forwardLines(stream, destination) {
  let pending = '';
  stream.on('data', chunk => {
    pending += chunk.toString();
    const lines = pending.split('\n');
    pending = lines.pop();
    for (const line of lines) destination.write(`${redact(line)}\n`);
  });
  stream.on('end', () => { if (pending) destination.write(redact(pending)); });
}

function run(command, args, env = state.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: repoRoot, env, stdio: ['ignore', 'pipe', 'pipe'],
      timeout: 180_000, killSignal: 'SIGKILL' });
    forwardLines(child.stdout, process.stdout);
    forwardLines(child.stderr, process.stderr);
    child.once('error', () => reject(new Error(`Acceptance ${command} command could not start`)));
    child.once('close', (code, signal) => code === 0 ? resolve() : reject(new Error(
      signal ? `Acceptance ${command} command terminated (${signal})` : `Acceptance ${command} command exited with code ${code}`)));
  });
}

function dockerOutput(args, options = {}) {
  return new Promise((resolve, reject) => {
    execFile('docker', args, { cwd: repoRoot, env: state.env, timeout: options.timeout || 30_000,
      maxBuffer: 10 * 1024 * 1024 }, (error, stdout) => error
      ? reject(new Error(`Owned Docker operation failed: ${redact(error.stderr || error.message)}`))
      : resolve(stdout));
  });
}

function reservePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
  });
}

function composeArgs(project, ...args) {
  return ['compose', '--progress', 'json', '--project-name', project,
    ...[...composeFiles, ...(state.extraComposeFiles || [])].flatMap(file => ['--file', file]), ...args];
}

async function waitForApplication(baseUrl) {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/api/v1/utils/health-check/`, { signal: AbortSignal.timeout(5_000) });
      if (response.ok) return;
    } catch { /* Startup only: never recovery by replacing a live stack. */ }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error('Acceptance application did not become ready within its startup deadline');
}

function controlHeaders(token = state.resetToken, run = state.projectName) {
  return { Authorization: `Bearer ${token}`, 'X-Acceptance-Run': run, 'Content-Type': 'application/json' };
}

async function controlRequest(endpoint, { method = 'GET', data, token = state.resetToken,
  run = state.projectName, timeout = (state.resetTimeoutSeconds || 60) * 1000 + 15_000 } = {}) {
  const response = await fetch(`${state.baseUrl}/api/v1/testing/acceptance/${endpoint}`, {
    method, headers: controlHeaders(token, run), signal: AbortSignal.timeout(timeout),
    ...(data === undefined ? {} : { body: JSON.stringify(data) }),
  });
  let body;
  try { body = await response.json(); } catch { body = {}; }
  return { ok: response.ok, status: response.status, body };
}

async function controlState() {
  const result = await controlRequest('state');
  if (!result.ok || result.body.run_id !== state.projectName) throw new Error('Owned acceptance control state could not be verified');
  state.generation = result.body.generation;
  return result.body;
}

async function startApplication(options = {}) {
  if (!state.stopped) throw new Error('An acceptance invocation cannot start a second stack');
  const port = await reservePort();
  const project = `sdd-acceptance-${process.pid}-${randomBytes(4).toString('hex')}`;
  state.resetEnabled = (options.resetEnabled ?? true) && (options.acceptanceMode ?? true);
  state.resetTimeoutSeconds = options.resetTimeoutSeconds ?? 60;
  state.resetToken = randomBytes(32).toString('hex');
  state.extraComposeFiles = options.extraComposeFiles || [];
  state.env = { ...process.env, COMPOSE_PROJECT_NAME: project, ACCEPTANCE_PORT: String(port),
    PROJECT_NAME: 'SDD Acceptance', SECRET_KEY: 'acceptance-secret-key-not-for-production',
    FIRST_SUPERUSER: 'admin@example.com', FIRST_SUPERUSER_PASSWORD: 'acceptance-admin-password',
    POSTGRES_PASSWORD: 'acceptance-postgres-password', SMTP_HOST: '', PREVIEW_ORIGIN: `http://preview.app.localhost:${port}`,
    FRONTEND_HOST: `http://app.localhost:${port}`,
    EMAILS_FROM_EMAIL: 'test@example.com', OPENAI_API_KEY: 'acceptance-provider-key',
    DEMO_GITHUB_REPO: demoRepository, DEMO_GITHUB_TOKEN: demoToken,
    DEVELOP_ACCEPTANCE_MODE: String(options.acceptanceMode ?? true),
    DEVELOP_ACCEPTANCE_RESET_ENABLED: String(state.resetEnabled), ACCEPTANCE_RUN_ID: project,
    ACCEPTANCE_RESET_TOKEN: state.resetToken, ACCEPTANCE_RESET_TIMEOUT_SECONDS: String(state.resetTimeoutSeconds),
    ACCEPTANCE_AGENT_ROOT: '/acceptance-agent-state' };
  // Browser and preview share a loopback site for HTTP cookies; Node/API clients
  // keep the numeric loopback address and do not depend on wildcard DNS.
  Object.assign(state, { projectName: project, baseUrl: `http://127.0.0.1:${port}`,
    browserBaseUrl: state.env.FRONTEND_HOST,
    demoRepositoryAvailable: undefined, generation: 0, fatal: undefined,
    events: [], stopped: false });
  record('stack-start');
  try {
    await run('docker', composeArgs(project, 'up', '--build', '--detach', 'db'));
    await run('docker', composeArgs(project, 'run', '--build', '--rm', 'backend', 'bash', 'scripts/prestart.sh'));
    await run('docker', composeArgs(project, 'up', '--build', '--detach', '--wait', 'backend'));
    await waitForApplication(state.baseUrl);
    state.demoRepositoryAvailable = true;
    record('stack-ready');
  } catch (error) {
    try { await stopApplication(); } catch (cleanupError) { error.cause = cleanupError; }
    throw error;
  }
}

async function ownedResources(project = state.projectName) {
  const resources = {};
  for (const [name, args] of [
    ['containers', ['ps', '-aq']], ['networks', ['network', 'ls', '-q']],
    ['volumes', ['volume', 'ls', '-q']], ['images', ['image', 'ls', '-q']],
  ]) {
    resources[name] = [...new Set((await dockerOutput([...args, '--filter', `label=sdd.preview.project=${project}`]))
      .split(/\s+/).filter(Boolean))];
  }
  return resources;
}

async function removeOwnedPreviewResources() {
  const resources = await ownedResources();
  for (const [kind, command] of [['containers', ['rm', '-f']], ['networks', ['network', 'rm']],
    ['volumes', ['volume', 'rm']], ['images', ['image', 'rm', '-f']]]) {
    for (const id of resources[kind]) await dockerOutput([...command, id]);
  }
}

async function assertOwnedResourcesRemoved(project = state.projectName) {
  for (const label of ['com.docker.compose.project', 'sdd.preview.project']) {
    for (const [kind, args] of [['containers', ['ps', '-aq']], ['networks', ['network', 'ls', '-q']],
      ['volumes', ['volume', 'ls', '-q']]]) {
      if ((await dockerOutput([...args, '--filter', `label=${label}=${project}`])).trim()) {
        throw new Error(`Owned acceptance ${kind} remain after final teardown`);
      }
    }
  }
}

let stopping;
async function stopApplication() {
  if (stopping) return stopping;
  if (!state.projectName || state.stopped) return;
  stopping = (async () => {
    const start = Date.now();
    const errors = [];
    const down = () => run('docker', composeArgs(state.projectName, 'down', '--volumes', '--remove-orphans'));
    let producersStopped = false;
    // Stop producers before deleting their resources or mounted checkouts. This
    // is final invocation teardown, never scenario-boundary recovery.
    try {
      await run('docker', composeArgs(state.projectName, 'stop', '--timeout', '10', 'backend', 'preview-controller'));
      producersStopped = true;
    } catch (error) {
      errors.push(error);
      try { await down(); producersStopped = true; } catch (error) { errors.push(error); }
    }
    if (producersStopped) {
      try { await removeOwnedPreviewResources(); } catch (error) { errors.push(error); }
    }
    // A dynamic-resource cleanup error must not strand the Compose stack.
    try { await down(); producersStopped = true; } catch (error) { errors.push(error); }
    if (producersStopped) {
      try { await removeOwnedPreviewResources(); } catch (error) { errors.push(error); }
    }
    try {
      await assertOwnedResourcesRemoved();
      state.stopped = true;
      state.demoRepositoryAvailable = undefined;
      record('stack-stopped', { milliseconds: Date.now() - start, ownedResourcesEmpty: true });
    } catch (error) { errors.push(error); }
    if (errors.length) {
      record('teardown-failed', { ownedResourcesEmpty: state.stopped });
      throw new AggregateError(errors, 'Owned acceptance final teardown encountered a failure');
    }
  })();
  try { return await stopping; } finally { stopping = undefined; }
}

async function showApplicationLogs() {
  if (!state.projectName || state.stopped) return;
  await run('docker', composeArgs(state.projectName, 'logs', '--no-color', 'backend', 'preview-controller'));
}

async function backendPythonOutput(code, ...args) {
  return dockerOutput(composeArgs(state.projectName, 'exec', '--no-TTY', 'backend', 'python', '-c', code, ...args), { timeout: 120_000 });
}

async function runBackendPython(code, ...args) {
  const output = await backendPythonOutput(code, ...args);
  if (output) process.stdout.write(output);
}

async function resetScenarioState() {
  if (state.fatal) throw new Error('Acceptance invocation has already failed its reset/control boundary');
  const start = Date.now();
  try {
    const previous = await controlState();
    const resetId = randomUUID();
    const result = await controlRequest('reset', { method: 'POST', data: {
      run_id: state.projectName, reset_id: resetId, expected_generation: previous.generation,
    } });
    if (!result.ok || result.body.run_id !== state.projectName || result.body.reset_id !== resetId ||
        result.body.generation !== previous.generation + 1 || !result.body.baseline_verified || result.body.phase !== 'ready') {
      const failed = await controlRequest('state').catch(() => ({ body: {} }));
      const phase = failed.body.failure_phase || result.body.phase || 'unverified';
      const error = new Error(`Acceptance reset failed (${phase}, HTTP ${result.status})`);
      error.phase = phase;
      throw error;
    }
    state.generation = result.body.generation;
    state.demoRepositoryAvailable = true;
    record('reset-ready', { generation: state.generation, milliseconds: Date.now() - start, phases: result.body.phases });
    return result.body;
  } catch (error) {
    state.fatal = error;
    record('reset-failed', { phase: error.phase || 'control', milliseconds: Date.now() - start });
    throw error;
  }
}

async function configureDemoRepository(available) {
  const start = Date.now();
  if (state.fatal) throw new Error('Acceptance invocation is closed after a boundary failure');
  try {
    const current = await controlState();
    const mode = available ? 'available' : 'unavailable';
    if (current.configuration !== mode) {
      const result = await controlRequest('configuration', { method: 'PATCH', data: {
        run_id: state.projectName, expected_generation: current.generation, mode,
      } });
      if (!result.ok) throw new Error(`Acceptance configuration verification failed (HTTP ${result.status})`);
      const verified = await controlState();
      if (verified.configuration !== mode) throw new Error('Acceptance effective configuration was not applied');
      record('configuration', { mode, generation: verified.generation, milliseconds: Date.now() - start });
    }
    state.demoRepositoryAvailable = available;
  } catch (error) {
    state.fatal = error;
    record('configuration-failed');
    throw error;
  }
}

module.exports = { backendPythonOutput, configureDemoRepository, controlHeaders, controlRequest,
  controlState, dockerOutput, composeArgs, ownedResources, assertOwnedResourcesRemoved, record,
  resetScenarioState, runBackendPython, showApplicationLogs, startApplication, state,
  stopApplication, redact };
