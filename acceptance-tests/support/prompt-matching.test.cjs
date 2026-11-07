'use strict';

const assert = require('node:assert/strict');
const { test } = require('node:test');
const { ApiClient } = require('./api-client.js');
const { PreviewWorkloadPage } = require('./pages/preview-workload-page.js');

function fixture(status = 200) {
  const posts = [];
  const world = { openApiContext: async () => ({ post: async (url, options) => {
    posts.push({ url, ...options });
    return { ok: () => status === 200, status: () => status };
  } }) };
  const api = new ApiClient(world);
  world.apiClient = api;
  return { api, world, posts };
}

function rules(posts) {
  assert.equal(posts.length, 1);
  assert.equal(posts[0].url, '/api/v1/testing/llm/control');
  assert.deepEqual(Object.keys(posts[0].data), ['rules']);
  return posts[0].data.rules;
}

const delayed = [{ kind: 'delay', delay_seconds: 10, text: 'finished' }];

test('agent rules explicitly match latest input and isolate title/planner delays', async () => {
  const { api, posts } = fixture();
  await api.configureFakeLlm({ prompt: '/openspec explore café', replies: delayed });
  assert.deepEqual(rules(posts), [
    { phase: 'title', replies: [{ kind: 'text', text: 'Acceptance chat' }] },
    { phase: 'planner', replies: [{ kind: 'text', text: 'null' }] },
    { phase: 'agent', prompt: `"/openspec explore café"`, replies: delayed },
  ]);
});

test('native OpenCode wire matching preserves literal quotes, newlines and Unicode', async () => {
  const { api, posts } = fixture();
  const prompt = '/openspec explore café "quoted"\nsecond line';
  await api.configureFakeLlm({ prompt, replies: [{ kind: 'text', text: 'mapped' }] });
  const wireText = rules(posts)[2].prompt;
  assert.equal(wireText, `"${prompt}"`);
  assert.notEqual(wireText, JSON.stringify(prompt));
});

test('concurrent chat commands get independent explicit match keys', async () => {
  const { api, posts } = fixture();
  const prompts = ['/openspec explore Capacity turn 0', '/openspec explore Capacity turn 1'];
  await api.configureFakeLlm({ prompt: prompts, replies: delayed });
  assert.deepEqual(rules(posts).filter(rule => rule.phase === 'agent'),
    prompts.map(prompt => ({ phase: 'agent', prompt: `"${prompt}"`, replies: delayed })));
});

test('tool sequences do not use the first reply as a title', async () => {
  const { api, posts } = fixture();
  const replies = [
    { kind: 'tool', tool_name: 'bash', tool_arguments: { command: 'true' } },
    { kind: 'text', text: 'done' },
  ];
  await api.configureFakeLlm({ prompt: '/openspec apply', replies, title: 'Update README' });
  assert.deepEqual(rules(posts)[0], { phase: 'title', replies: [{ kind: 'text', text: 'Update README' }] });
  assert.deepEqual(rules(posts)[2].replies, replies);
});

for (const options of [
  { replies: delayed }, { prompt: 'missing replies' },
  { prompt: '', replies: delayed }, { prompt: ['same', 'same'], replies: delayed },
  { prompt: [null], replies: delayed },
]) {
  test(`invalid implicit/ambiguous agent mapping rejects before HTTP: ${JSON.stringify(options)}`, async () => {
    const { api, posts } = fixture();
    await assert.rejects(api.configureFakeLlm(options), /distinct, explicit prompts/);
    assert.deepEqual(posts, []);
  });
}

test('configuration failure propagates', async () => {
  const { api } = fixture(422);
  await assert.rejects(api.configureFakeLlm({ plan: null }), /configure fake LLM: 422/);
});

test('proposal matching uses the complete stored message conversation, not old commands or proposals', async () => {
  const { api, posts } = fixture();
  api.listDevelopmentMessages = async (token, chatId) => {
    assert.equal(token, 'token'); assert.equal(chatId, 'chat');
    return { has_more: false, next_cursor: null, data: [
      { kind: 'message', role: 'user', content: '  Initial question  ' },
      { kind: 'message', role: 'assistant', content: 'Canonical findings' },
      { kind: 'message', role: 'user', content: '\n' },
      { kind: 'proposal', role: 'assistant', content: 'Not conversation' },
    ] };
  };
  await api.configureFakeProposal('token', 'chat', 'A proposal');
  assert.deepEqual(rules(posts)[2], {
    phase: 'agent', prompt: '"/openspec propose user: Initial question\nassistant: Canonical findings"',
    replies: [{ kind: 'text', text: 'A proposal' }],
  });
});

test('proposal streaming fixtures preserve exact prompt matching and delayed chunks', async () => {
  const { api, posts } = fixture();
  api.listDevelopmentMessages = async () => ({ has_more: false, data: [
    { kind: 'message', role: 'user', content: 'Inspect repository' },
  ] });
  await api.configureFakeProposal('token', 'chat', 'partial complete', {
    stream_chunk_size: 8, stream_chunk_delay_seconds: 8,
  });
  assert.deepEqual(rules(posts)[2], {
    phase: 'agent', prompt: '"/openspec propose user: Inspect repository"',
    replies: [{ kind: 'text', text: 'partial complete', stream_chunk_size: 8, stream_chunk_delay_seconds: 8 }],
  });
});

test('proposal fixture applies the configured default conversation tail bound', async () => {
  const { api, posts } = fixture();
  api.listDevelopmentMessages = async () => ({ has_more: false, next_cursor: null, data: [
    { kind: 'message', role: 'user', content: 'x'.repeat(100_001) },
  ] });
  await api.configureFakeProposal('token', 'chat', 'proposal');
  assert.equal(rules(posts)[2].prompt, `"/openspec propose ${'x'.repeat(100_000)}"`);
});

test('proposal fixtures reject truncated history instead of scripting an approximate prompt', async () => {
  const { api, posts } = fixture();
  api.listDevelopmentMessages = async () => ({ has_more: true, next_cursor: 'older', data: [] });
  await assert.rejects(api.configureFakeProposal('token', 'chat', 'proposal'), /complete conversation/);
  assert.deepEqual(posts, []);
});

for (const planKind of ['website', 'api-only', 'null']) {
  test(`preview instruction fixture retains real planner output: ${planKind}`, async () => {
    const { world, posts } = fixture();
    const page = new PreviewWorkloadPage(world);
    const plan = planKind === 'null' ? null : page.documentedPlan();
    if (planKind === 'api-only') plan.website = null;
    await page.selectInstructions(plan);
    const configured = rules(posts);
    assert.equal(configured.filter(rule => rule.phase === 'agent').length, 0);
    assert.deepEqual(configured.find(rule => rule.phase === 'planner').replies,
      [{ kind: 'text', text: JSON.stringify(plan) }]);
  });
}

test('preview completion keeps its edit window but supplies an immediate real planner reply separately', async () => {
  const { api, world, posts } = fixture();
  const operations = [];
  api.request = async (_token, method, url, options) => {
    operations.push(['turn', method, url, options.data.content]);
    return { status: () => 200, text: async () => '' };
  };
  api.waitForAgentTurn = async () => { operations.push(['active']); };
  api.editWorkspaceFile = async (chatId, file) => { operations.push(['edit', chatId, file]); };
  const page = new PreviewWorkloadPage(world);
  await page.completedTurn('chat', 'site/feature.js');
  const configured = rules(posts);
  assert.deepEqual(configured.find(rule => rule.phase === 'agent'), {
    phase: 'agent', prompt: '"/openspec explore Edit checkout"',
    replies: [{ kind: 'delay', delay_seconds: 3, text: 'Turn finished' }],
  });
  assert.equal(configured.find(rule => rule.phase === 'planner').replies[0].text, JSON.stringify(page.documentedPlan()));
  assert.deepEqual(operations, [
    ['turn', 'post', '/api/v1/develop/chats/chat/messages/explore/stream', 'Edit checkout'],
    ['active'], ['edit', 'chat', 'site/feature.js'],
  ]);
});
