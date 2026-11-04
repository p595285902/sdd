'use strict';
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const test = require('node:test');
const { BoundedCommand } = require('./bounded-command.cjs');

test('a real runner deadline sends cancellation and joins cleanup before failing', async () => {
  const command = new BoundedCommand(process.execPath, ['-e', `
    process.on('SIGTERM', () => { process.stdout.write('owned cleanup completed'); process.exit(0); });
    setInterval(() => {}, 20);
  `], { stdio: ['ignore', 'pipe', 'pipe'] }, { timeout: 200, cleanupTimeout: 1000 });
  let captured = '';
  command.child.stdout.on('data', chunk => { captured += chunk; });
  await assert.rejects(command.execute(), /invocation deadline/);
  assert.equal(command.closed, true);
  assert.match(captured, /owned cleanup completed/);
  await command.stop();
});

test('a cancelled real runner is joined without waiting for the execution deadline', async () => {
  const command = new BoundedCommand(process.execPath, ['-e', 'setInterval(() => {}, 20)'],
    { stdio: ['ignore', 'pipe', 'pipe'] }, { timeout: 1000, cleanupTimeout: 1000 });
  await Promise.all([command.stop(), command.stop()]);
  assert.equal(command.closed, true);
});

test('unproven cleanup has a finite deadline and retains child ownership', async () => {
  const child = Object.assign(new EventEmitter(), { stdout: new PassThrough(), stderr: new PassThrough() });
  const signals = [];
  child.kill = signal => { signals.push(signal); return true; };
  const command = new BoundedCommand('fixture', [], {}, { spawnProcess: () => child, timeout: 5, cleanupTimeout: 5 });
  try {
    await assert.rejects(command.execute(), /cleanup deadline.*ownership remains retained/);
    assert.equal(command.closed, false);
    assert.equal(command.child, child);
    assert.deepEqual(signals, ['SIGTERM']);
    await assert.rejects(command.stop(), /cleanup deadline/);
  } finally { child.stdout.end(); child.stderr.end(); child.emit('close', 1, null); }
});

test('a launch failure becomes an explicit runner failure, not missing green reports', async () => {
  const child = Object.assign(new EventEmitter(), { stdout: new PassThrough(), stderr: new PassThrough(), kill() {} });
  const command = new BoundedCommand('fixture', [], {}, { spawnProcess: () => child, timeout: 1000 });
  queueMicrotask(() => { child.emit('error', new Error('private launch detail')); child.emit('close', -1, null); });
  await assert.rejects(command.execute(), /could not be launched/);
  assert.equal(command.closed, true);
});
