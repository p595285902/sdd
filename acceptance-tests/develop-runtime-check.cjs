const assert = require('node:assert/strict');
const { execFile } = require('node:child_process');
const path = require('node:path');
const { promisify } = require('node:util');

const execFileAsync = promisify(execFile);
const repoRoot = path.resolve(__dirname, '..');
const backendImage = 'backend:latest';
const workspaceTarget = '/develop-workspaces';
const volumeName = `sdd-develop-runtime-check-${process.pid}-${Date.now()}`;
const composeEnvironment = {
  ...process.env,
  PROJECT_NAME: 'SDD runtime check',
  SECRET_KEY: 'runtime-check-secret',
  FIRST_SUPERUSER: 'runtime-check@example.com',
  FIRST_SUPERUSER_PASSWORD: 'runtime-check-password',
  POSTGRES_PASSWORD: 'runtime-check-postgres-password',
};

async function run(command, args, options = {}) {
  return execFileAsync(command, args, {
    cwd: repoRoot,
    env: composeEnvironment,
    maxBuffer: 10 * 1024 * 1024,
    ...options,
  });
}

async function inspectComposeConfiguration() {
  const { stdout } = await run('docker', [
    'compose',
    '--file',
    'compose.yml',
    'config',
    '--format',
    'json',
  ]);
  const configuration = JSON.parse(stdout);
  const backend = configuration.services.backend;
  const workspaceMount = backend.volumes.find(
    ({ target }) => target === workspaceTarget,
  );

  assert.equal(backend.environment.DEVELOP_WORKSPACE_ROOT, workspaceTarget);
  assert.equal(workspaceMount.type, 'volume');
  assert.equal(workspaceMount.source, 'sdd-develop-workspaces');
  assert.ok(configuration.volumes['sdd-develop-workspaces']);
  assert.equal(
    backend.labels['traefik.http.services.backend.loadbalancer.responseforwarding.flushinterval'],
    '-1ms',
  );
}

async function inspectImage() {
  const { stdout: commandOutput } = await run('docker', [
    'image',
    'inspect',
    backendImage,
    '--format',
    '{{json .Config.Cmd}}',
  ]);
  assert.deepEqual(JSON.parse(commandOutput), [
    'fastapi',
    'run',
    '--workers',
    '1',
  ]);

  const { stdout: versionOutput } = await run('docker', [
    'run',
    '--rm',
    '--entrypoint',
    'sh',
    backendImage,
    '-ec',
    'git --version && opencode --version && openspec --version',
  ]);
  const versions = versionOutput.trim().split('\n');
  assert.match(versions[0], /^git version /);
  assert.equal(versions[1], '1.18.23');
  assert.equal(versions[2], '1.13.0');
}

async function inspectWorkspacePersistence() {
  await run('docker', ['volume', 'create', volumeName]);
  try {
    const mount = `type=volume,source=${volumeName},target=${workspaceTarget}`;
    await run('docker', [
      'run',
      '--rm',
      '--mount',
      mount,
      '--entrypoint',
      'sh',
      backendImage,
      '-ec',
      `test -w ${workspaceTarget} && printf persistent > ${workspaceTarget}/replacement-check`,
    ]);
    await run('docker', [
      'run',
      '--rm',
      '--mount',
      mount,
      '--entrypoint',
      'sh',
      backendImage,
      '-ec',
      `test "$(cat ${workspaceTarget}/replacement-check)" = persistent`,
    ]);
  } finally {
    await run('docker', ['volume', 'rm', volumeName]);
  }
}

async function main() {
  await inspectComposeConfiguration();
  await inspectImage();
  await inspectWorkspacePersistence();
  console.log('Develop runtime checks passed.');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});