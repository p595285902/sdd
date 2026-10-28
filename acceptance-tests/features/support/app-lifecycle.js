const { execFile, spawn } = require('node:child_process');
const net = require('node:net');
const path = require('node:path');

const repoRoot = path.resolve(__dirname, '../../..');
const composeFiles = [
  path.join(repoRoot, 'compose.yml'),
  path.join(repoRoot, 'acceptance-tests/compose.yml'),
];

const state = {
  baseUrl: undefined,
  projectName: undefined,
  backendId: undefined,
  demoRepositoryAvailable: undefined,
  backendRecreations: 0,
};

const demoRepository = 'https://example.com/acceptance/demo-repository.git';
const demoToken = 'acceptance-token';

function run(command, args, env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: repoRoot,
      env,
      stdio: 'inherit',
    });
    child.once('error', reject);
    child.once('exit', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${command} ${args.join(' ')} exited with code ${code}`));
    });
  });
}

function dockerOutput(args) {
  return new Promise((resolve, reject) => {
    execFile('docker', args, { cwd: repoRoot, env: state.env, timeout: 10_000 }, (error, stdout) => {
      if (error) reject(error);
      else resolve(stdout);
    });
  });
}

function reservePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

function composeArgs(projectName, ...args) {
  return [
    'compose',
    '--progress',
    'json',
    '--project-name',
    projectName,
    '--file',
    composeFiles[0],
    '--file',
    composeFiles[1],
    ...args,
  ];
}

async function waitForApplication(baseUrl) {
  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/api/v1/utils/health-check/`, {
        signal: AbortSignal.timeout(5_000),
      });
      if (response.ok) return;
    } catch {
      // The container may still be starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Acceptance application did not become ready at ${baseUrl}`);
}

function setDemoRepository(available) {
  state.env.DEMO_GITHUB_REPO = available ? demoRepository : '';
  state.env.DEMO_GITHUB_TOKEN = available ? demoToken : 'incomplete-demo-token';
}

async function backendInfo() {
  const id = await dockerOutput(composeArgs(state.projectName, 'ps', '-q', 'backend'));
  if (!id.trim()) return null;
  const stdout = await dockerOutput(['inspect', '--format', '{{json .}}', id.trim()]);
  const container = JSON.parse(stdout);
  const environment = Object.fromEntries(
    container.Config.Env.map((entry) => {
      const separator = entry.indexOf('=');
      return [entry.slice(0, separator), entry.slice(separator + 1)];
    }),
  );
  return {
    id: container.Id,
    healthy: container.State.Running && container.State.Health?.Status === 'healthy',
    repo: environment.DEMO_GITHUB_REPO,
    token: environment.DEMO_GITHUB_TOKEN,
  };
}

async function verifyBackend(available) {
  const backend = await backendInfo();
  if (!backend?.healthy ||
      backend.repo !== state.env.DEMO_GITHUB_REPO ||
      backend.token !== state.env.DEMO_GITHUB_TOKEN) {
    throw new Error('Acceptance backend is not healthy with the requested demo repository configuration');
  }
  await waitForApplication(state.baseUrl);
  state.backendId = backend.id;
  state.demoRepositoryAvailable = available;
}

async function startApplication() {
  const port = await reservePort();
  const projectName = `sdd-acceptance-${process.pid}`;
  const env = {
    ...process.env,
    ACCEPTANCE_PORT: String(port),
    PROJECT_NAME: 'SDD Acceptance',
    SECRET_KEY: 'acceptance-secret-key-not-for-production',
    FIRST_SUPERUSER: 'admin@example.com',
    FIRST_SUPERUSER_PASSWORD: 'acceptance-admin-password',
    POSTGRES_PASSWORD: 'acceptance-postgres-password',
    SMTP_HOST: '',
    PREVIEW_ORIGIN: 'http://preview.localhost',
    EMAILS_FROM_EMAIL: 'test@example.com',
    OPENAI_API_KEY: 'acceptance-provider-key',
    DEMO_GITHUB_REPO: demoRepository,
    DEMO_GITHUB_TOKEN: demoToken,
  };

  state.projectName = projectName;
  state.baseUrl = `http://127.0.0.1:${port}`;
  state.env = env;
  state.backendId = undefined;
  state.demoRepositoryAvailable = undefined;
  state.backendRecreations = 0;

  await run('docker', composeArgs(projectName, 'up', '--build', '--detach', 'db'), env);
  await run(
    'docker',
    composeArgs(
      projectName,
      'run',
      '--build',
      '--rm',
      'backend',
      'bash',
      'scripts/prestart.sh',
    ),
    env,
  );
  await run(
    'docker',
    composeArgs(projectName, 'up', '--build', '--detach', '--wait', 'backend'),
    env,
  );
  await waitForApplication(state.baseUrl);
  await verifyBackend(true);
}

async function stopApplication() {
  if (!state.projectName) return;
  await run(
    'docker',
    composeArgs(state.projectName, 'down', '--volumes', '--remove-orphans'),
    state.env,
  );
  state.backendId = undefined;
  state.demoRepositoryAvailable = undefined;
}

async function showApplicationLogs() {
  if (!state.projectName) return;
  await run(
    'docker',
    composeArgs(state.projectName, 'logs', '--no-color', 'backend'),
    state.env,
  );
}

async function runBackendPython(code, ...args) {
  await run(
    'docker',
    composeArgs(
      state.projectName,
      'exec',
      '--no-TTY',
      'backend',
      'python',
      '-c',
      code,
      ...args,
    ),
    state.env,
  );
}

async function configureDemoRepository(available) {
  setDemoRepository(available);
  const backend = await backendInfo();
  if (state.demoRepositoryAvailable === available &&
      backend?.id === state.backendId &&
      backend.healthy &&
      backend.repo === state.env.DEMO_GITHUB_REPO &&
      backend.token === state.env.DEMO_GITHUB_TOKEN) {
    try {
      const response = await fetch(`${state.baseUrl}/api/v1/utils/health-check/`, {
        signal: AbortSignal.timeout(5_000),
      });
      if (response.ok) return;
    } catch {
      // The owned backend is no longer reachable; recreate it below.
    }
  }
  state.backendId = undefined;
  state.demoRepositoryAvailable = undefined;
  await run(
    'docker',
    composeArgs(
      state.projectName,
      'up',
      '--detach',
      '--force-recreate',
      '--wait',
      'backend',
    ),
    state.env,
  );
  state.backendRecreations += 1;
  console.log(`[acceptance-stack] backend recreation ${state.backendRecreations}`);
  await verifyBackend(available);
}

module.exports = {
  backendInfo,
  configureDemoRepository,
  runBackendPython,
  showApplicationLogs,
  startApplication,
  state,
  stopApplication,
};