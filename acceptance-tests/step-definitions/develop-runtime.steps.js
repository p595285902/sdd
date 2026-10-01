const { Given, Then, When } = require('@cucumber/cucumber');
const assert = require('node:assert/strict');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');

const execFileAsync = promisify(execFile);
const backendImage = 'backend:latest';

async function inspectImageCommand() {
  const { stdout } = await execFileAsync('docker', [
    'image',
    'inspect',
    backendImage,
    '--format',
    '{{json .Config.Cmd}}',
  ]);
  return JSON.parse(stdout);
}

Given('the production backend image is built', async function () {
  const { stdout } = await execFileAsync('docker', [
    'image',
    'inspect',
    backendImage,
    '--format',
    '{{.Id}}',
  ]);
  assert.match(stdout.trim(), /^sha256:[a-f0-9]+$/);
});

When('its Develop tool versions are inspected', async function () {
  const { stdout } = await execFileAsync('docker', [
    'run',
    '--rm',
    '--entrypoint',
    'sh',
    backendImage,
    '-c',
    'git --version && opencode --version && openspec --version',
  ]);
  this.developToolVersions = stdout.trim().split('\n');
});

Then('git is available', function () {
  assert.match(this.developToolVersions[0], /^git version /);
});

Then('opencode is available', function () {
  assert.equal(this.developToolVersions[1], '1.18.23');
});

Then('openspec is available', function () {
  assert.equal(this.developToolVersions[2], '1.13.0');
});

Given('the production backend configuration is loaded', async function () {
  this.productionBackendCommand = await inspectImageCommand();
});

When('the backend service starts', function () {
  assert.deepEqual(this.productionBackendCommand.slice(0, 2), ['fastapi', 'run']);
});

Then('exactly one FastAPI worker is configured', function () {
  const workerFlags = this.productionBackendCommand
    .map((value, index, command) => value === '--workers' ? command[index + 1] : undefined)
    .filter(Boolean);
  assert.deepEqual(workerFlags, ['1']);
});