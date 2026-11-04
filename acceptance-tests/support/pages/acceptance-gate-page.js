'use strict';
const assert = require('node:assert/strict');
const { BoundedCommand } = require('../bounded-command.cjs');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const cheerio = require('cheerio');
const { discover } = require('../acceptance-inventory.cjs');
const { redact } = require('../../features/support/app-lifecycle.js');

const acceptanceRoot = path.resolve(__dirname, '../..');
const normal = `#### Scenario: Fixture normal configuration\n\n\`\`\`gherkin
Given an acceptance run has a backend with the demo repository configured
When successive scenarios request that same repository configuration
Then the backend is not recreated between those requests
And each scenario retains its fresh browser context and independent test state
\`\`\`\n`;
const lifecycle = `### Requirement: Fresh-run lifecycle remains unchanged
Each invocation MUST retain independently verified project ownership and teardown.

#### Scenario: Fixture separate lifecycle

\`\`\`gherkin
Given the default acceptance suite starts a fresh project-scoped stack
When its scenarios finish
Then only that run's project is torn down
And a subsequent full-suite run starts a separate fresh project
\`\`\`\n`;

class AcceptanceGatePage {
  constructor(world) { this.world = world; this.prefixes = []; this.executions = []; }
  write(relative, content) {
    const filename = path.join(this.root, relative);
    fs.mkdirSync(path.dirname(filename), { recursive: true });
    fs.writeFileSync(filename, content);
  }
  async composeFixture() {
    this.root = fs.mkdtempSync(path.join(os.tmpdir(), 'sdd-gate-fixture-'));
    this.source = `# Acceptance stack reuse\n\n## Requirements\n\n### Requirement: Unchanged acceptance configuration reuses the backend within a run\nNormal scenarios MUST use the owned stack and independent state.\n\n${normal}\n${lifecycle}`;
    this.delta = `# Acceptance stack reuse\n\n## MODIFIED Requirements\n\n### Requirement: Unchanged acceptance configuration reuses the backend within a run\nNormal scenarios MUST use the unchanged owned stack with verified reset.\n\n${normal.replace('Fixture normal configuration', 'Fixture effective normal configuration')}`;
    this.write('specs/acceptance-stack-reuse/spec.md', this.source);
    this.write('changes/fixture-change/specs/acceptance-stack-reuse/spec.md', this.delta);
    // Historical and nested backlog material must not become active inventory.
    this.write('changes/archive/old/specs/acceptance-stack-reuse/spec.md', this.delta.replace('Fixture effective normal configuration', 'Historical scenario must not execute'));
    this.write('changes/backlog/old/specs/acceptance-stack-reuse/spec.md', this.delta.replace('Fixture effective normal configuration', 'Backlog scenario must not execute'));
    this.inventory = this.discover();
    assert.equal(this.inventory.entries.length, 2);
    assert.deepEqual(this.inventory.entries.map(entry => entry.group).sort(), ['lifecycle', 'normal']);
  }
  discover(sourceOnly = false) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'sdd-gate-discovery-'));
    try { return discover({ specRoot: this.root, extractedRoot: path.join(directory, '.extracted'), sourceOnly }); }
    finally { fs.rmSync(directory, { recursive: true, force: true }); }
  }
  async execute({ sourceOnly = false, dryRun = false } = {}) {
    const prefix = `fixture-${randomUUID()}`;
    this.prefixes.push(prefix);
    const args = [path.join(acceptanceRoot, 'acceptance-gate.cjs'), '--spec-root', this.root, '--report-prefix', prefix];
    if (sourceOnly) args.push('--source-only');
    if (dryRun) args.push('--dry-run');
    assert.ok(!this.command || this.command.closed, 'An earlier command still owns an unfinished invocation');
    this.command = new BoundedCommand(process.execPath, args, { cwd: acceptanceRoot,
      stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, ACCEPTANCE_EVENT_LOG: '' } });
    let result;
    try {
      result = await this.command.execute();
      result.output = redact(result.output);
    } finally {
      if (this.command.closed) this.command = undefined;
    }
    const reportRoot = path.join(acceptanceRoot, 'reports');
    const summary = JSON.parse(fs.readFileSync(path.join(reportRoot, `${prefix}-summary.json`), 'utf8'));
    const features = JSON.parse(fs.readFileSync(path.join(reportRoot, `${prefix}-results.json`), 'utf8'));
    const html = fs.readFileSync(path.join(reportRoot, `${prefix}-report.html`), 'utf8');
    const events = Object.fromEntries(['normal', 'lifecycle'].map(group => {
      const filename = path.join(reportRoot, `${prefix}-${group}-events.ndjson`);
      return [group, fs.existsSync(filename) ? fs.readFileSync(filename, 'utf8').split('\n').filter(Boolean).map(line => JSON.parse(line)) : []];
    }));
    const execution = { ...result, prefix, summary, features, html, events };
    this.executions.push(execution);
    return execution;
  }
  async runComplete() {
    this.success = await this.execute();
    assert.equal(this.success.code, 0, this.success.output.slice(-8000));
    assert.equal(this.success.summary.status, 'passed');
    assert.equal(this.success.summary.complete, true);
  }
  async expectExactGroups() {
    const { summary, features } = this.success;
    assert.equal(summary.assigned, 2);
    assert.equal(new Set(summary.assignments.map(entry => entry.id)).size, 2);
    assert.deepEqual(summary.groups.map(group => group.group), ['normal', 'lifecycle']);
    for (const group of summary.groups) {
      assert.equal(group.assigned, 1);
      assert.equal(group.reported, 1);
      assert.equal(group.passed, 1);
      assert.deepEqual(group.missing, []);
    }
    const names = features.flatMap(feature => feature.elements || []).filter(element => element.type === 'scenario').map(element => element.name);
    assert.equal(names.length, new Set(names).size);
    assert.ok(names.includes('Fixture effective normal configuration'));
    assert.ok(!names.includes('Fixture normal configuration'));
    assert.ok(!names.some(name => name.includes('Historical') || name.includes('Backlog')));
    const source = this.discover(true);
    assert.ok(source.entries.some(entry => entry.name === 'Fixture normal configuration'));
    assert.ok(source.entries.every(entry => !entry.uri.includes('/changes/')));
  }
  async expectOrderedTeardown() {
    const normalEvents = this.success.events.normal;
    const lifecycleEvents = this.success.events.lifecycle;
    const stopped = normalEvents.filter(event => event.type === 'stack-stopped');
    const starts = lifecycleEvents.filter(event => event.type === 'stack-start');
    assert.equal(stopped.length, 1);
    assert.ok(stopped[0].ownedResourcesEmpty);
    assert.ok(starts.length >= 2, 'Real separate lifecycle invocations did not emit startup evidence');
    assert.ok(starts.every(event => event.at >= stopped[0].at), 'Dedicated lifecycle started before normal final teardown');
  }
  async expectFailurePropagation() {
    this.write('changes/fixture-change/specs/acceptance-stack-reuse/spec.md', this.delta.replace('Then the backend is not recreated between those requests', 'Then that scenario uses a backend with the demo repository unconfigured'));
    const normalFailed = await this.execute();
    assert.notEqual(normalFailed.code, 0);
    assert.equal(normalFailed.summary.status, 'failed');
    assert.equal(normalFailed.summary.groups[0].status, 'failed');
    assert.equal(normalFailed.summary.groups[1].status, 'not-run-after-failure');
    assert.deepEqual(normalFailed.events.lifecycle, []);
    this.write('changes/fixture-change/specs/acceptance-stack-reuse/spec.md', this.delta);
    this.write('specs/acceptance-stack-reuse/spec.md', this.source.replace('Then only that run\'s project is torn down', 'Then those invocations use distinct project-scoped stacks'));
    const lifecycleFailed = await this.execute();
    assert.notEqual(lifecycleFailed.code, 0);
    assert.equal(lifecycleFailed.summary.status, 'failed');
    assert.equal(lifecycleFailed.summary.groups[0].status, 'passed');
    assert.equal(lifecycleFailed.summary.groups[1].status, 'failed');
    this.write('specs/acceptance-stack-reuse/spec.md', this.source);
    const armed = normal.replace('Fixture normal configuration', 'Fixture arms terminal boundary')
      .replace('When successive scenarios request that same repository configuration', 'When the isolated command fixture arms a bounded filesystem cleanup fault')
      .replace('And each scenario retains its fresh browser context and independent test state\n', '');
    const later = normal.replace('Fixture normal configuration', 'Fixture must not enter after failed boundary');
    const skipped = normal.replace('Fixture normal configuration', 'Fixture must not run after fatal abort');
    const header = this.delta.slice(0, this.delta.indexOf('#### Scenario:'));
    this.write('changes/fixture-change/specs/acceptance-stack-reuse/spec.md', `${header}${armed}\n${later}\n${skipped}`);
    const fatal = await this.execute();
    assert.notEqual(fatal.code, 0);
    assert.equal(fatal.summary.status, 'failed');
    assert.equal(fatal.summary.assigned, 4);
    assert.equal(fatal.summary.groups[0].status, 'failed');
    assert.equal(fatal.summary.groups[1].status, 'not-run-after-failure');
    assert.equal(fatal.summary.groups[0].allPassed, false);
    assert.deepEqual(fatal.events.lifecycle, []);
    const admitted = fatal.events.normal.filter(event => event.type === 'scenario-start');
    assert.deepEqual(admitted.map(event => event.scenario), ['Fixture arms terminal boundary']);
    assert.ok(fatal.events.normal.some(event => event.type === 'reset-failed' && event.phase === 'cleaning_files'));
    const stops = fatal.events.normal.filter(event => event.type === 'stack-stopped');
    assert.equal(stops.length, 1);
    assert.equal(stops[0].ownedResourcesEmpty, true);
    this.write('changes/fixture-change/specs/acceptance-stack-reuse/spec.md', this.delta);
  }
  async expectHtml() {
    const $ = cheerio.load(this.success.html);
    assert.equal($('h1').text(), 'Acceptance gate: passed');
    const rows = $('tbody tr').toArray().map(row => $(row).find('td').first().text());
    assert.deepEqual(rows, ['normal', 'lifecycle']);
    assert.equal($('tbody a').length, 2);
    assert.equal($('h2').filter((_, element) => $(element).text() === 'Assignments').length, 1);
    assert.equal($('ul li').length, 2);
    for (const execution of this.executions.filter(result => result.code !== 0)) {
      assert.ok(cheerio.load(execution.html)('h1').text().includes('failed'));
    }
  }
  async addNewScenario() {
    await this.composeFixture();
    await this.runComplete();
    this.historical = this.success.summary;
    this.newName = 'Newly discovered fixture scenario';
    this.write('changes/fixture-change/specs/acceptance-stack-reuse/spec.md', `${this.delta}\n${normal.replace('Fixture normal configuration', this.newName)}`);
  }
  async freshDiscovery() {
    this.fresh = await this.execute();
    assert.equal(this.fresh.code, 0, this.fresh.output.slice(-8000));
    this.inventory = this.discover();
  }
  async expectNewScenario() {
    const matches = this.fresh.summary.assignments.filter(entry => entry.name === this.newName);
    assert.equal(matches.length, 1);
    assert.equal(matches[0].group, 'normal');
    assert.equal(this.fresh.summary.assigned, 3);
    assert.equal(this.fresh.summary.groups.find(group => group.group === 'normal').passed, 2);
  }
  async expectIndependentDiscovery() {
    assert.equal(this.historical.assigned, 2);
    assert.equal(this.fresh.summary.assigned, 3);
    assert.notEqual(this.historical.fingerprint, this.fresh.summary.fingerprint);
    assert.equal(this.inventory.entries.filter(entry => entry.name === this.newName).length, 1);
    // Delete a historical summary: fresh composition still discovers the new scenario.
    const old = path.join(acceptanceRoot, 'reports', `${this.success.prefix}-summary.json`);
    fs.rmSync(old, { force: true });
    assert.equal(this.discover().entries.filter(entry => entry.name === this.newName).length, 1);
  }
  async dispose() {
    if (this.command) await this.command.stop();
    if (this.root) fs.rmSync(this.root, { recursive: true, force: true });
  }
}
module.exports = { AcceptanceGatePage };
