'use strict';

// Owns one fresh Docker Compose stack per suite invocation: a unique project
// name and a free host port, migrations plus the first superuser, a health
// poll, and teardown with volumes. Runs on the host, so the suite starts with
// a single command (`npm test`).
//
// The backend image serves the built frontend, so the app under test is the
// real full stack; only `db` and `backend` are started (see compose.yml here).

const { spawnSync } = require('node:child_process');
const net = require('node:net');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const COMPOSE_FILES = ['-f', 'compose.yml', '-f', 'acceptance-tests/compose.yml'];
const HEALTH_CHECK_PATH = '/api/v1/utils/health-check/';
const HEALTH_TIMEOUT_MS = 120_000;

// Values the root compose file interpolates. They are passed to every compose
// command because interpolation happens per file, before the override is
// merged; compose.yml here only adds the acceptance-specific wiring.
// First-superuser and database passwords must not be "changethis" — the app
// rejects defaults outside development.
const STACK_ENV = {
  PROJECT_NAME: 'Acceptance Tests',
  SECRET_KEY: 'acceptance-tests-secret-key',
  FIRST_SUPERUSER: 'admin@example.com',
  FIRST_SUPERUSER_PASSWORD: 'acceptance-password',
  POSTGRES_PASSWORD: 'acceptance',
  SMTP_HOST: '',
  SMTP_USER: '',
  SMTP_PASSWORD: '',
  EMAILS_FROM_EMAIL: 'info@example.com',
  SENTRY_DSN: '',
};

let stack = null;

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

function compose(args, { allowFailure = false } = {}) {
  const result = spawnSync(
    'docker',
    ['compose', '-p', stack.project, ...COMPOSE_FILES, ...args],
    { cwd: REPO_ROOT, env: stack.env, stdio: 'inherit' }
  );
  if (result.error) throw result.error;
  if (result.status !== 0 && !allowFailure) {
    throw new Error(
      `docker compose ${args.join(' ')} failed with exit code ${result.status}`
    );
  }
  return result.status;
}

async function waitForHealth(url) {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 1_000));
  }
  throw new Error(
    `Backend did not become healthy at ${url} within ${HEALTH_TIMEOUT_MS / 1000}s: ${lastError}`
  );
}

// Boots the stack. Safe to call once per process; `stop()` always tears down
// whatever reached the host, including volumes.
async function start() {
  if (stack) return stack.baseUrl;

  const port = await findFreePort();
  const project = `sdd-acceptance-${process.pid}-${Date.now().toString(36)}`;
  stack = {
    project,
    baseUrl: `http://127.0.0.1:${port}`,
    env: { ...process.env, ...STACK_ENV, ACCEPTANCE_PORT: String(port) },
  };

  compose(['build', 'backend']);
  compose(['up', '-d', '--wait', 'db']);
  compose(['run', '--rm', '-T', 'backend', 'bash', 'scripts/prestart.sh']);
  compose(['up', '-d', '--wait', 'backend']);

  try {
    await waitForHealth(`${stack.baseUrl}${HEALTH_CHECK_PATH}`);
  } catch (error) {
    compose(['logs', '--no-color', '--tail', '200', 'backend'], {
      allowFailure: true,
    });
    throw error;
  }
  return stack.baseUrl;
}

async function stop() {
  if (!stack) return;
  compose(['down', '--volumes', '--remove-orphans'], { allowFailure: true });
  stack = null;
}

function getBaseUrl() {
  if (!stack) throw new Error('The acceptance stack is not running');
  return stack.baseUrl;
}

// Safety net: if the suite crashes before AfterAll, still remove containers
// and volumes. The handler must be synchronous.
process.once('exit', () => {
  if (!stack) return;
  spawnSync(
    'docker',
    ['compose', '-p', stack.project, ...COMPOSE_FILES, 'down', '--volumes', '--remove-orphans'],
    { cwd: REPO_ROOT, env: stack.env, stdio: 'ignore' }
  );
});

module.exports = { start, stop, getBaseUrl };
