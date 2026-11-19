'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const { test } = require('node:test');

function worldClass(fatal = false) {
  const file = path.join(__dirname, 'world.js');
  const originalRequire = createRequire(file);
  const module = { exports: {} };
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), { module, require(name) {
    if (name === '@cucumber/cucumber') return { World: class {}, setWorldConstructor() {} };
    if (name === './app-lifecycle.js') return { state: { fatal } };
    return originalRequire(name);
  } }, { filename: file });
  return module.exports.AcceptanceWorld;
}

test('scenario cleanup closes polling/stream clients before stopping preview workloads', async () => {
  const World = worldClass();
  const world = Object.create(World.prototype);
  const order = [];
  world.disposeContexts = async () => { order.push('clients'); };
  world.previewWorkloadPage = { async stopAll() { order.push('previews'); } };
  await world.dispose();
  assert.deepEqual(order, ['clients', 'previews']);
});

test('client cleanup failure still attempts owned preview teardown and stays a failure', async () => {
  const World = worldClass();
  const world = Object.create(World.prototype);
  let stopped = false;
  world.disposeContexts = async () => { throw new Error('Client disposal failed'); };
  world.previewWorkloadPage = { async stopAll() { stopped = true; } };
  await assert.rejects(world.dispose(), /Client disposal failed/);
  assert.equal(stopped, true);
});

test('fatal run-wide cancellation retains its existing shared teardown ownership', async () => {
  const World = worldClass(true);
  const world = Object.create(World.prototype);
  let clientsClosed = false;
  world.disposeContexts = async () => { clientsClosed = true; };
  world.previewWorkloadPage = { async stopAll() { throw new Error('Run-wide cleanup owns cancelled workloads'); } };
  await world.dispose();
  assert.equal(clientsClosed, true);
});
