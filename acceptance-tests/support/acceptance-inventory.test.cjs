'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');
const { discover, executionGroup, groupPaths } = require('./acceptance-inventory.cjs');

function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'sdd-inventory-test-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const root = path.join(directory, 'openspec');
  fs.mkdirSync(root);
  return {
    root,
    write(relative, content) { const file = path.join(root, relative); fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, content); },
    discover(options = {}) { return discover({ specRoot: root, extractedRoot: path.join(directory, '.extracted'), ...options }); },
  };
}
function spec({ capability = 'Example', requirement = 'Example requirement', scenario = 'Example scenario', steps = 'Given example state\nWhen example operation\nThen example result', operation } = {}) {
  return `# ${capability}\n\n## ${operation ? `${operation} Requirements` : 'Requirements'}\n\n### Requirement: ${requirement}\nThe application MUST satisfy this example requirement.\n\n#### Scenario: ${scenario}\n\n\`\`\`gherkin\n${steps}\n\`\`\`\n`;
}
test('classification keeps fresh lifecycle and terminal validation out of normal scenarios', () => {
  assert.equal(executionGroup('acceptance-stack-reuse', 'Fresh-run lifecycle remains unchanged', 'fresh'), 'lifecycle');
  assert.equal(executionGroup('acceptance-stack-reuse', 'Separate validation groups retain complete effective-spec coverage', 'gate'), 'lifecycle');
  assert.equal(executionGroup('acceptance-state-reset', 'Unverified reset fails the invocation without a replacement stack', 'failure'), 'lifecycle');
  assert.equal(executionGroup('acceptance-state-reset', 'Reset controls are restricted to the owned acceptance run', 'Reset controls are unavailable outside acceptance mode'), 'lifecycle');
  assert.equal(executionGroup('acceptance-state-reset', 'Reset controls are restricted to the owned acceptance run', 'An unauthenticated reset cannot change state'), 'normal');
});
test('canonical active deltas supersede source, while source-only stays pristine and historical roots stay excluded', t => {
  const tree = fixture(t);
  tree.write('specs/example/spec.md', spec({ scenario: 'Source case' }));
  tree.write('changes/current/specs/example/spec.md', spec({ scenario: 'Delta case', operation: 'MODIFIED' }));
  tree.write('changes/archive/old/specs/example/spec.md', spec({ scenario: 'Archived case', operation: 'ADDED' }));
  tree.write('changes/backlog/old/specs/example/spec.md', spec({ scenario: 'Backlog case', operation: 'ADDED' }));
  assert.deepEqual(tree.discover().entries.map(entry => entry.name), ['Delta case']);
  assert.deepEqual(tree.discover({ sourceOnly: true }).entries.map(entry => entry.name), ['Source case']);
});
test('every invocation refreshes extraction and stable identities do not depend on report or extraction path', t => {
  const tree = fixture(t);
  tree.write('specs/example/spec.md', spec());
  const first = tree.discover();
  fs.writeFileSync(path.join(first.extractedRoot, 'stale.feature'), 'stale generated output');
  const again = tree.discover({ extractedRoot: path.join(first.extractedRoot, '../another-extraction') });
  assert.equal(first.entries[0].id, again.entries[0].id);
  tree.write('specs/example/spec.md', spec({ scenario: 'Newly added case' }));
  const fresh = tree.discover();
  assert.equal(fs.existsSync(path.join(fresh.extractedRoot, 'stale.feature')), false);
  assert.notEqual(fresh.fingerprint, first.fingerprint);
  assert.deepEqual(fresh.entries.map(entry => entry.name), ['Newly added case']);
});
test('duplicate semantic scenarios, conflicting deltas and empty inventories reject rather than disappear', t => {
  const duplicate = fixture(t);
  duplicate.write('specs/example/spec.md', `${spec()}\n#### Scenario: Example scenario\n\n\`\`\`gherkin\nGiven example state\nWhen example operation\nThen example result\n\`\`\`\n`);
  assert.throws(() => duplicate.discover(), /Duplicate/);
  const conflict = fixture(t);
  conflict.write('specs/example/spec.md', spec());
  for (const change of ['one', 'two']) conflict.write(`changes/${change}/specs/example/spec.md`, spec({ operation: 'MODIFIED' }));
  assert.throws(() => conflict.discover(), /supersed|conflict|multiple/i);
  assert.throws(() => fixture(t).discover(), /empty inventory/);
});
test('scenario outlines assign example rows independently with correct line selectors', t => {
  const tree = fixture(t);
  const content = `# Example\n\n## Requirements\n\n### Requirement: Outline requirement\nEach example MUST be discovered independently.\n\n#### Scenario Outline: Outline <value>\n\n\`\`\`gherkin\nGiven state <value>\nWhen operation runs\nThen result is <value>\nExamples:\n  | value |\n  | one |\n  | two |\n\`\`\`\n`;
  tree.write('specs/example/spec.md', content);
  const inventory = tree.discover();
  assert.deepEqual(inventory.entries.map(entry => entry.name), ['Outline one', 'Outline two']);
  assert.equal(new Set(inventory.entries.map(entry => entry.id)).size, 2);
  assert.deepEqual(inventory.entries.map(entry => entry.line), [16, 17]);
  assert.ok(groupPaths(inventory.entries, 'normal')[0].endsWith(':16:17'));
});
module.exports = { fixture, spec };
