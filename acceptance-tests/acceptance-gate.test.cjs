'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { test } = require('node:test');
const cheerio = require('cheerio');
const { auditGroup, parseArguments, runGate } = require('./acceptance-gate.cjs');
const { AcceptanceGatePage } = require('./support/pages/acceptance-gate-page.js');
const root = __dirname;
function scenarioReport(entries, status = 'passed') {
  return entries.map(entry => ({ uri: entry.uri, elements: [{ type: 'scenario', line: entry.line, name: entry.name,
    steps: entry.steps.map(name => ({ name, result: { status } })) }] }));
}
function setup(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'sdd-gate-unit-'));
  const specRoot = path.join(directory, 'openspec');
  const folder = path.join(specRoot, 'specs/acceptance-stack-reuse');
  fs.mkdirSync(folder, { recursive: true });
  const content = `# Acceptance stack reuse\n\n## Requirements\n\n### Requirement: Unchanged acceptance configuration reuses the backend within a run\nThe normal cases MUST retain their shared stack.\n\n#### Scenario: Normal case\n\n\`\`\`gherkin\nGiven normal state\nWhen operation runs\nThen operation succeeds\n\`\`\`\n\n### Requirement: Fresh-run lifecycle remains unchanged\nEvery invocation MUST retain fresh ownership.\n\n#### Scenario: Lifecycle case\n\n\`\`\`gherkin\nGiven lifecycle state\nWhen invocation completes\nThen ownership is verified\n\`\`\`\n`;
  fs.writeFileSync(path.join(folder, 'spec.md'), content);
  const prefix = `unit-${randomUUID()}`;
  t.after(() => {
    fs.rmSync(directory, { recursive: true, force: true });
    for (const file of fs.readdirSync(path.join(root, 'reports'))) if (file.startsWith(prefix)) fs.rmSync(path.join(root, 'reports', file), { force: true });
  });
  return { specRoot, prefix };
}
test('argument parsing preserves explicit partial/dry/source choices and rejects unknown options', () => {
  assert.deepEqual(parseArguments(['--source-only', '--group', 'normal', '--dry-run', '--name', 'case', '--format', 'json:example.json']), { names: ['case'], formats: ['json:example.json'], sourceOnly: true, group: 'normal', dryRun: true });
  assert.throws(() => parseArguments(['--parallel', '2']), /Unsupported/);
  assert.throws(() => parseArguments(['--group', 'other']), /group/);
  assert.throws(() => parseArguments(['--report-prefix', '../outside']), /basename/);
});
test('result audit rejects missing, duplicate, unassigned and truncated scenario coverage', () => {
  const entries = [{ id: 'case', uri: path.join(root, 'fixture.feature'), line: 4, name: 'Case', steps: ['state', 'operation', 'result'] }];
  assert.equal(auditGroup(entries, scenarioReport(entries)).allPassed, true);
  assert.equal(auditGroup(entries, []).allPassed, false);
  assert.throws(() => auditGroup(entries, [...scenarioReport(entries), ...scenarioReport(entries)]), /twice/);
  assert.throws(() => auditGroup(entries, scenarioReport([{ ...entries[0], name: 'Other case' }])), /Unassigned/);
  const truncated = scenarioReport(entries);
  truncated[0].elements[0].steps.pop();
  assert.throws(() => auditGroup(entries, truncated), /step|incomplete/i);
});
test('real Cucumber hidden Before/After results do not conflict with Gherkin coverage and still fail the gate', () => {
  const entries = [{ id: 'case', uri: path.join(root, 'fixture.feature'), line: 4, name: 'Case', steps: ['state', 'operation', 'result'] }];
  const report = scenarioReport(entries);
  const steps = report[0].elements[0].steps;
  steps.unshift({ keyword: 'Before', hidden: true, result: { status: 'passed' } });
  steps.push({ keyword: 'After', hidden: true, result: { status: 'passed' } });
  assert.equal(auditGroup(entries, report).allPassed, true);
  steps.at(-1).result.status = 'failed';
  assert.equal(auditGroup(entries, report).allPassed, false);
  steps.at(-1).result.status = 'passed';
  steps.splice(2, 1);
  assert.throws(() => auditGroup(entries, report), /step coverage/);
});
test('complete gate runs disjoint groups serially and reports all assigned results', async t => {
  const options = setup(t);
  let active = false;
  const order = [];
  const summary = await runGate(options, async ({ group, entries }) => {
    assert.equal(active, false); active = true; order.push(`start:${group}`);
    await new Promise(resolve => setImmediate(resolve));
    active = false; order.push(`finish:${group}`);
    return { code: 0, wallSeconds: 1, features: scenarioReport(entries) };
  });
  assert.deepEqual(order, ['start:normal', 'finish:normal', 'start:lifecycle', 'finish:lifecycle']);
  assert.equal(summary.status, 'passed'); assert.equal(summary.complete, true);
  assert.equal(summary.assigned, 2);
  assert.deepEqual(summary.groups.map(group => [group.group, group.passed]), [['normal', 1], ['lifecycle', 1]]);
  const $ = cheerio.load(fs.readFileSync(path.join(root, 'reports', `${options.prefix}-report.html`), 'utf8'));
  assert.equal($('tbody tr').length, 2); assert.equal($('ul li').length, 2);
});
test('normal failure prevents a separate group from starting and retains its incomplete assignment', async t => {
  const options = setup(t), ran = [];
  const summary = await runGate(options, async ({ group, entries }) => { ran.push(group); return { code: 1, wallSeconds: 1, features: scenarioReport(entries, 'failed') }; });
  assert.deepEqual(ran, ['normal']); assert.equal(summary.status, 'failed');
  assert.equal(summary.groups[1].status, 'not-run-after-failure'); assert.equal(summary.groups[1].missing.length, 1);
});
test('separate group failure makes the combined gate fail even if all normal cases pass', async t => {
  const summary = await runGate(setup(t), async ({ group, entries }) => ({ code: group === 'normal' ? 0 : 1, wallSeconds: 1, features: scenarioReport(entries, group === 'normal' ? 'passed' : 'failed') }));
  assert.equal(summary.status, 'failed'); assert.equal(summary.groups[0].status, 'passed'); assert.equal(summary.groups[1].status, 'failed');
});
test('success exit with missing reports cannot become a green gate', async t => {
  const summary = await runGate(setup(t), async () => ({ code: 0, wallSeconds: 1, features: [] }));
  assert.equal(summary.status, 'failed'); assert.equal(summary.groups[0].missing.length, 1);
});
test('executor/audit errors still explicitly report every assigned group as failed or incomplete', async t => {
  const summary = await runGate(setup(t), async () => { throw new Error('Malformed or missing JSON report'); });
  assert.equal(summary.status, 'failed');
  assert.equal(summary.groups.length, 2);
  assert.deepEqual(summary.groups.map(group => group.status), ['failed', 'not-run-after-failure']);
});
test('standalone groups and dry runs are never complete acceptance success', async t => {
  const execute = async ({ entries }) => ({ code: 0, wallSeconds: 0, features: scenarioReport(entries) });
  const partial = await runGate({ ...setup(t), group: 'normal' }, execute);
  assert.equal(partial.status, 'partial-pass'); assert.equal(partial.complete, false); assert.equal(partial.groups.length, 1);
  const dry = await runGate({ ...setup(t), dryRun: true }, async ({ entries }) => ({ code: 0, wallSeconds: 0, features: scenarioReport(entries, 'skipped') }));
  assert.equal(dry.status, 'dry-run'); assert.equal(dry.complete, false);
});
test('source-only uses fresh source inventory and unselected empty groups reject', async t => {
  const options = setup(t);
  const summary = await runGate({ ...options, sourceOnly: true }, async ({ entries }) => ({ code: 0, wallSeconds: 0, features: scenarioReport(entries) }));
  assert.equal(summary.sourceOnly, true);
  const source = path.join(options.specRoot, 'specs/acceptance-stack-reuse/spec.md');
  fs.writeFileSync(source, fs.readFileSync(source, 'utf8').split('### Requirement: Fresh-run lifecycle remains unchanged')[0]);
  await assert.rejects(runGate({ ...options, group: 'lifecycle' }, async () => { throw new Error('Must not execute empty group'); }), /No acceptance scenario/);
});
test('isolated command fixtures retain bindings without historical repository specs', { timeout: 60_000 }, async t => {
  const page = new AcceptanceGatePage({});
  t.after(() => page.dispose());
  await page.composeFixture();
  const variants = [
    [page.delta, page.source],
    [page.delta.replace('Then the backend is not recreated between those requests',
      'Then that scenario uses a backend with the demo repository unconfigured'), page.source],
    [page.delta, page.source.replace("Then only that run's project is torn down",
      'Then those invocations use distinct project-scoped stacks')],
    [page.delta.replace('When successive scenarios request that same repository configuration',
      'When the isolated command fixture arms a bounded filesystem cleanup fault'), page.source],
  ];
  for (const [delta, source] of variants) {
    page.write('changes/fixture-change/specs/acceptance-stack-reuse/spec.md', delta);
    page.write('specs/acceptance-stack-reuse/spec.md', source);
    const execution = await page.execute({ dryRun: true });
    assert.equal(execution.code, 0, execution.output);
    assert.equal(execution.summary.status, 'dry-run');
    assert.deepEqual(execution.summary.groups.map(group => group.group), ['normal', 'lifecycle']);
    const scenarios = execution.features.flatMap(feature => feature.elements || [])
      .filter(element => element.type === 'scenario');
    assert.equal(scenarios.length, 2);
    for (const scenario of scenarios) {
      assert.ok(scenario.steps.length);
      for (const step of scenario.steps) assert.equal(step.result.status, 'skipped',
        `Command fixture has an undefined or ambiguous step: ${step.name}`);
    }
  }
});
