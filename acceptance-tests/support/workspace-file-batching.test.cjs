const assert = require('node:assert/strict');
const { after, beforeEach, mock, test } = require('node:test');
const lifecycle = require('../features/support/app-lifecycle.js');

// ApiClient captures this function when its module loads. No Docker is used here.
const python = mock.method(lifecycle, 'runBackendPython', async () => {});
const { ApiClient } = require('./api-client.js');
const { PreviewWorkloadPage } = require('./pages/preview-workload-page.js');

beforeEach(() => {
  python.mock.resetCalls();
  python.mock.mockImplementation(async () => {});
});
after(() => python.mock.restore());

function recordedWrites() {
  return python.mock.calls.flatMap(({ arguments: [, chatId, ...args] }) => {
    const files = args.length === 1 ? JSON.parse(args[0]) : [args];
    return files.map(([name, content]) => [chatId, name, content]);
  });
}

test('standalone edits are immediate, including while another chat has a batch', async () => {
  const client = new ApiClient({});
  await client.editWorkspaceFile('first', 'before', 'immediate');
  assert.equal(python.mock.callCount(), 1);
  await client.withWorkspaceFileBatch('first', async () => {
    await client.editWorkspaceFile('first', 'queued', 'batched');
    assert.equal(python.mock.callCount(), 1);
    await client.editWorkspaceFile('second', 'other', 'immediate');
    assert.equal(python.mock.callCount(), 2);
  });
  await client.editWorkspaceFile('first', 'after', 'immediate');
  assert.deepEqual(recordedWrites(), [
    ['first', 'before', 'immediate'], ['second', 'other', 'immediate'],
    ['first', 'queued', 'batched'], ['first', 'after', 'immediate'],
  ]);
});

test('one batch preserves order, overwrites, empty content, Unicode and callback result', async () => {
  const client = new ApiClient({});
  const files = [['nested/a.txt', 'first'], ['empty', ''], ['nested/a.txt', 'café\nsecond\n']];
  const result = await client.withWorkspaceFileBatch('chat', async () => {
    for (const [name, content] of files) await client.editWorkspaceFile('chat', name, content);
    assert.equal(python.mock.callCount(), 0);
    return 'prepared';
  });
  assert.equal(result, 'prepared');
  assert.equal(python.mock.callCount(), 1);
  assert.deepEqual(recordedWrites(), files.map(([name, content]) => ['chat', name, content]));
});

test('nested preparation for the same chat joins its enclosing batch', async () => {
  const client = new ApiClient({});
  await client.withWorkspaceFileBatch('chat', async () => {
    await client.editWorkspaceFile('chat', 'file', 'first');
    await client.withWorkspaceFileBatch('chat', async () => {
      await client.editWorkspaceFile('chat', 'file', 'nested');
    });
    assert.equal(python.mock.callCount(), 0);
    await client.editWorkspaceFile('chat', 'file', 'last');
  });
  assert.equal(python.mock.callCount(), 1);
  assert.deepEqual(recordedWrites().map(([, , content]) => content), ['first', 'nested', 'last']);
});

test('nested preparations for different chats flush independently', async () => {
  const client = new ApiClient({});
  await client.withWorkspaceFileBatch('first', async () => {
    await client.editWorkspaceFile('first', 'a', 'outer');
    await client.withWorkspaceFileBatch('second', () => client.editWorkspaceFile('second', 'b', 'inner'));
    assert.equal(python.mock.callCount(), 1);
    await client.editWorkspaceFile('first', 'c', 'outer');
  });
  assert.equal(python.mock.callCount(), 2);
  assert.deepEqual(recordedWrites(), [
    ['second', 'b', 'inner'], ['first', 'a', 'outer'], ['first', 'c', 'outer'],
  ]);
});

test('separate and concurrent async preparations never share a batch', async () => {
  const client = new ApiClient({});
  const prepare = chatId => client.withWorkspaceFileBatch(chatId, async () => {
    await client.editWorkspaceFile(chatId, 'a', chatId);
    await Promise.resolve();
    await client.editWorkspaceFile(chatId, 'b', chatId);
  });
  await Promise.all([prepare('same'), prepare('same'), prepare('other')]);
  await prepare('later');
  assert.equal(python.mock.callCount(), 4);
  for (const { arguments: [, chatId, payload] } of python.mock.calls) {
    assert.deepEqual(JSON.parse(payload), [['a', chatId], ['b', chatId]]);
  }
});

test('a different client cannot join a batch for the same chat', async () => {
  const first = new ApiClient({});
  const second = new ApiClient({});
  await first.withWorkspaceFileBatch('chat', async () => {
    await first.editWorkspaceFile('chat', 'a', 'first client');
    await second.editWorkspaceFile('chat', 'b', 'second client');
    assert.equal(python.mock.callCount(), 1);
  });
  assert.deepEqual(recordedWrites(), [['chat', 'b', 'second client'], ['chat', 'a', 'first client']]);
});

test('empty preparations do not invoke Python', async () => {
  const client = new ApiClient({});
  assert.equal(await client.withWorkspaceFileBatch('chat', async () => 42), 42);
  assert.equal(python.mock.callCount(), 0);
});

test('preparation failure discards queued writes and does not contaminate the next batch', async () => {
  const client = new ApiClient({});
  await assert.rejects(client.withWorkspaceFileBatch('chat', async () => {
    await client.editWorkspaceFile('chat', 'old', 'discarded');
    throw new Error('preparation failed');
  }), /preparation failed/);
  assert.equal(python.mock.callCount(), 0);
  await client.withWorkspaceFileBatch('chat', () => client.editWorkspaceFile('chat', 'new', 'saved'));
  assert.deepEqual(recordedWrites(), [['chat', 'new', 'saved']]);
});

test('Python failure propagates and does not contaminate the next batch', async () => {
  const client = new ApiClient({});
  python.mock.mockImplementation(async () => { throw new Error('fixture write failed'); });
  await assert.rejects(client.withWorkspaceFileBatch('chat', () =>
    client.editWorkspaceFile('chat', 'old', 'failed')), /fixture write failed/);
  python.mock.resetCalls();
  python.mock.mockImplementation(async () => {});
  await client.withWorkspaceFileBatch('chat', () => client.editWorkspaceFile('chat', 'new', 'saved'));
  assert.deepEqual(recordedWrites(), [['chat', 'new', 'saved']]);
});

test('detached writes cannot silently append to a batch after it closes', async () => {
  const client = new ApiClient({});
  let release;
  let detached;
  await client.withWorkspaceFileBatch('chat', async () => {
    detached = new Promise(resolve => { release = resolve; }).then(() =>
      client.editWorkspaceFile('chat', 'late', 'not awaited'));
    await client.editWorkspaceFile('chat', 'ready', 'saved');
  });
  release();
  await assert.rejects(detached, /batch is closed/);
  assert.deepEqual(recordedWrites(), [['chat', 'ready', 'saved']]);
});

for (const [method, args] of [
  ['prepareInstructions', ['chat', 'website']],
  ['prepareInstructions', ['chat', 'timeout']],
  ['prepareInstructions', ['chat', 'missing']],
  ['prepareInstructions', ['chat', 'compose']],
  ['prepareCompose', ['chat']],
  ['prepareRoutingCompose', ['chat', 'Unicode café']],
  ['prepareDependencyCompose', ['chat']],
  ['prepareNpmDependencyCompose', ['chat']],
  ['prepareComposeDependencies', ['chat']],
]) {
  test(`fixture ${method} ${args[1] || ''} emits the same ordered writes in one call`, async () => {
    const expected = [];
    const immediate = new PreviewWorkloadPage({ apiClient: {
      withWorkspaceFileBatch: async (chatId, prepare) => prepare(),
      editWorkspaceFile: async (...write) => { expected.push(write); },
    } });
    await immediate[method](...args);
    const batched = new PreviewWorkloadPage({ apiClient: new ApiClient({}) });
    await batched[method](...args);
    assert.deepEqual(recordedWrites(), expected);
    assert.equal(python.mock.callCount(), 1);
  });
}
