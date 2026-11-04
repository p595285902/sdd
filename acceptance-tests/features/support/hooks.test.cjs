'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');
const { test } = require('node:test');

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
function fixture(startup, launch = async () => ({ close: async () => {} })) {
  const hooks = {};
  const calls = [];
  const state = {};
  const process = Object.assign(new EventEmitter(), { env: {} });
  const lifecycle = {
    state,
    startApplication: async () => { calls.push('start'); await startup; calls.push('started'); },
    stopApplication: async () => { calls.push('stop'); },
    record: type => calls.push(type),
  };
  const cucumber = {
    BeforeAll: (_options, hook) => { hooks.beforeAll = hook; },
    AfterAll: (_options, hook) => { hooks.afterAll = hook; },
    Before: () => {}, After: () => {}, Status: { FAILED: 'FAILED' }, setDefaultTimeout: () => {},
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'hooks.js'), 'utf8'), {
    process, console,
    require: name => name === '@playwright/test' ? { chromium: { launch } }
      : name === '@cucumber/cucumber' ? cucumber : lifecycle,
  }, { filename: 'hooks.js' });
  return { hooks, calls, process, state };
}

test('cancellation during application startup waits for creation to settle before owned teardown', async () => {
  const startup = deferred();
  let launched = false;
  const run = fixture(startup.promise, async () => { launched = true; });
  const before = run.hooks.beforeAll();
  const rejected = assert.rejects(before, /startup cancelled/);
  assert.equal(run.process.listenerCount('SIGTERM'), 1);
  run.process.emit('SIGTERM');
  assert.equal(run.calls.includes('stop'), false);
  startup.resolve();
  await rejected;
  await run.hooks.afterAll();
  assert.equal(launched, false);
  assert.deepEqual(run.calls, ['start', 'cancelled', 'started', 'stop']);
  assert.equal(run.process.exitCode, 143);
  assert.ok(run.state.fatal);
  assert.equal(run.process.listenerCount('SIGTERM'), 0);
  assert.equal(run.process.listenerCount('SIGINT'), 0);
});

test('cancellation during browser startup closes the browser before stack teardown', async () => {
  const browser = deferred();
  const run = fixture(Promise.resolve(), () => browser.promise);
  const before = run.hooks.beforeAll();
  const rejected = assert.rejects(before, /browser startup cancelled/);
  await new Promise(resolve => setImmediate(resolve));
  run.process.emit('SIGINT');
  assert.equal(run.calls.includes('stop'), false);
  browser.resolve({ close: async () => run.calls.push('browser-close') });
  await rejected;
  await run.hooks.afterAll();
  assert.ok(run.calls.indexOf('browser-close') < run.calls.indexOf('stop'));
  assert.equal(run.calls.filter(call => call === 'stop').length, 1);
  assert.equal(run.process.exitCode, 130);
});

test('browser startup failure still executes final owned teardown and removes signal handlers', async () => {
  const run = fixture(Promise.resolve(), async () => { throw new Error('Browser fixture failed'); });
  await assert.rejects(run.hooks.beforeAll(), /Browser fixture failed/);
  await run.hooks.afterAll();
  assert.equal(run.calls.filter(call => call === 'stop').length, 1);
  assert.equal(run.process.listenerCount('SIGTERM'), 0);
});
