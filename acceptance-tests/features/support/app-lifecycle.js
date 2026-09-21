const { spawn } = require('node:child_process');
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
};

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
      const response = await fetch(`${baseUrl}/api/v1/utils/health-check/`);
      if (response.ok) return;
    } catch {
      // The container may still be starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Acceptance application did not become ready at ${baseUrl}`);
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
    EMAILS_FROM_EMAIL: 'test@example.com',
  };

  state.projectName = projectName;
  state.baseUrl = `http://127.0.0.1:${port}`;
  state.env = env;

  await run('docker', composeArgs(projectName, 'up', '--build', '--detach', 'db'), env);
  await run(
    'docker',
    composeArgs(projectName, 'run', '--rm', 'backend', 'bash', 'scripts/prestart.sh'),
    env,
  );
  await run(
    'docker',
    composeArgs(projectName, 'up', '--build', '--detach', '--wait', 'backend'),
    env,
  );
  await waitForApplication(state.baseUrl);
}

async function stopApplication() {
  if (!state.projectName) return;
  await run(
    'docker',
    composeArgs(state.projectName, 'down', '--volumes', '--remove-orphans'),
    state.env,
  );
}

module.exports = { startApplication, state, stopApplication };