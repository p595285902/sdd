'use strict';
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { ApiClient } = require('./api-client.js');

function fixture() {
  const contexts = [];
  const world = { async openApiContext(headers) {
    const id = contexts.length;
    contexts.push({ id, headers });
    const perform = async (path, options) => ({ id, path, options, headers });
    return { get: perform, post: perform };
  } };
  return { world, contexts, client: new ApiClient(world) };
}

test('concurrent bearer requests reuse one scenario-local identity context', async () => {
  const { client, contexts } = fixture();
  const responses = await Promise.all([client.request('user-a', 'get', '/one'), client.request('user-a', 'post', '/two', { data: { value: 1 } })]);
  assert.equal(contexts.length, 1);
  assert.deepEqual(responses.map(response => response.id), [0, 0]);
  assert.equal(responses[1].options.data.value, 1);
});

test('different users and anonymous callers never share credentials', async () => {
  const { client, contexts } = fixture();
  await client.request('user-a', 'get', '/one');
  await client.request('user-b', 'get', '/two');
  await client.request(undefined, 'get', '/anonymous');
  assert.deepEqual(contexts.map(context => context.headers.Authorization), ['Bearer user-a', 'Bearer user-b', 'Bearer undefined']);
});

test('explicit cookie/origin/header probes retain fresh contexts', async () => {
  const { client, contexts } = fixture();
  const first = await client.request('user-a', 'get', '/one');
  const options = { headers: { Cookie: 'isolated-browser-session' } };
  const probe = await client.request('user-a', 'get', '/probe', options);
  const secondProbe = await client.request('user-a', 'get', '/probe', options);
  const again = await client.request('user-a', 'get', '/again');
  assert.equal(contexts.length, 3);
  assert.notEqual(probe.id, secondProbe.id);
  assert.notEqual(probe.id, first.id);
  assert.equal(again.id, first.id);
});

test('a fresh ApiClient/reset generation never inherits the previous context', async () => {
  const { client, world } = fixture();
  const first = await client.request('user-a', 'get', '/one');
  const next = new ApiClient(world);
  const second = await next.request('user-a', 'get', '/one');
  assert.notEqual(first.id, second.id);
});

test('context creation failures propagate without hidden retries or a poisoned cache', async () => {
  const { client, world, contexts } = fixture();
  const create = world.openApiContext;
  let reject = true;
  world.openApiContext = async headers => {
    if (reject) throw new Error('Context creation failed');
    return create(headers);
  };
  await assert.rejects(client.request('user-a', 'get', '/one'), /Context creation failed/);
  assert.equal(contexts.length, 0);
  reject = false;
  const response = await client.request('user-a', 'get', '/one');
  assert.equal(response.id, 0);
  assert.equal(contexts.length, 1);
});
