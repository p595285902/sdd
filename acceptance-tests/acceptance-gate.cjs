'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { discover, acceptanceRoot, groupPaths } = require('./support/acceptance-inventory.cjs');

function parseArguments(args) {
  const options = { names: [], formats: [] };
  for (let index = 0; index < args.length; index++) {
    const argument = args[index];
    if (argument === '--dry-run') options.dryRun = true;
    else if (argument === '--source-only') options.sourceOnly = true;
    else if (['--group', '--spec-root', '--report-prefix', '--name', '--format'].includes(argument)) {
      const value = args[++index];
      if (!value) throw new Error(`Missing value for ${argument}`);
      if (argument === '--name') options.names.push(value);
      else if (argument === '--format') options.formats.push(value);
      else options[{ '--group': 'group', '--spec-root': 'specRoot', '--report-prefix': 'prefix' }[argument]] = value;
    } else throw new Error(`Unsupported acceptance-gate option: ${argument}`);
  }
  if (options.group && !['normal', 'lifecycle'].includes(options.group)) throw new Error('Acceptance group must be normal or lifecycle');
  if (options.prefix && !/^[a-zA-Z0-9._-]+$/.test(options.prefix)) throw new Error('Acceptance report prefix must be a basename');
  return options;
}

function readScenarios(features) {
  return features.flatMap(feature => (feature.elements || []).filter(element => element.type === 'scenario')
    .map(scenario => ({ uri: path.resolve(acceptanceRoot, feature.uri), ...scenario })));
}

function auditGroup(entries, features, { dryRun = false } = {}) {
  const expected = new Map(entries.map(entry => [`${entry.uri}:${entry.line}:${entry.name}`, entry]));
  const observed = new Set();
  let passed = 0;
  for (const scenario of readScenarios(features)) {
    const key = `${scenario.uri}:${scenario.line}:${scenario.name}`;
    if (!expected.has(key)) throw new Error(`Unassigned acceptance scenario executed: ${scenario.name}`);
    if (observed.has(key)) throw new Error(`Acceptance scenario executed twice: ${scenario.name}`);
    observed.add(key);
    const expectedSteps = expected.get(key).steps;
    // Cucumber JSON embeds Before/After hook results in the scenario's step
    // array. Hooks still participate in pass/fail, but are not pickle steps.
    const gherkinSteps = (scenario.steps || []).filter(step =>
      !(step.hidden === true && ['Before', 'After'].includes(step.keyword)));
    if (JSON.stringify(gherkinSteps.map(step => step.name)) !== JSON.stringify(expectedSteps)) {
      throw new Error(`Incomplete or conflicting step coverage: ${scenario.name}`);
    }
    if (scenario.steps.length && scenario.steps.every(step => step.result?.status === 'passed')) passed++;
  }
  return { assigned: expected.size, reported: observed.size, passed,
    missing: [...expected].filter(([key]) => !observed.has(key)).map(([, entry]) => entry.id),
    allPassed: observed.size === expected.size && (dryRun || passed === expected.size) };
}

function executeCucumber({ group, manifestPath, reports, dryRun }) {
  return new Promise((resolve, reject) => {
    const started = process.hrtime.bigint();
    const args = [path.join(acceptanceRoot, 'node_modules/@cucumber/cucumber/bin/cucumber.js'),
      '--config', 'cucumber.cjs', '--profile', group,
      '--parallel', '0', '--retry', '0', '--fail-fast', '--format', 'progress',
      '--format', `json:${reports.json}`, '--format', `html:${reports.html}`];
    if (dryRun) args.push('--dry-run');
    const child = spawn(process.execPath, args, { cwd: acceptanceRoot, stdio: 'inherit', env: {
      ...process.env, ACCEPTANCE_MANIFEST_PATH: manifestPath, ACCEPTANCE_EVENT_LOG: reports.events,
    } });
    const cancel = signal => child.kill(signal);
    const interrupt = () => cancel('SIGINT');
    const terminate = () => cancel('SIGTERM');
    process.once('SIGINT', interrupt);
    process.once('SIGTERM', terminate);
    function unlisten() { process.removeListener('SIGINT', interrupt); process.removeListener('SIGTERM', terminate); }
    child.once('error', error => { unlisten(); reject(error); });
    child.once('close', (code, signal) => {
      unlisten();
      try {
        const features = fs.existsSync(reports.json) ? JSON.parse(fs.readFileSync(reports.json, 'utf8')) : [];
        resolve({ code: code ?? 1, signal, wallSeconds: Number(process.hrtime.bigint() - started) / 1e9, features });
      } catch { reject(new Error(`Acceptance ${group} report is malformed or incomplete`)); }
    });
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
}

function htmlReport(summary) {
  const rows = summary.groups.map(group => `<tr><td>${escapeHtml(group.group)}</td><td>${escapeHtml(group.status)}</td>` +
    `<td>${group.assigned}</td><td>${group.reported || 0}</td><td>${group.passed || 0}</td><td>${(group.wallSeconds || 0).toFixed(2)}s</td>` +
    `<td>${group.report ? `<a href="${escapeHtml(path.basename(group.report))}">HTML report</a>` : 'Not executed'}</td></tr>`).join('');
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
    `<title>Acceptance Gate</title><style>body{font:16px system-ui;background:#fff;color:#17202a;margin:32px;max-width:1100px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:10px;border-bottom:1px solid #ccd}code{overflow-wrap:anywhere}a{color:#145aa0}@media(max-width:600px){body{margin:16px}table{font-size:12px}td,th{padding:4px}}</style></head><body>` +
    `<h1>Acceptance gate: ${escapeHtml(summary.status)}</h1><p>${summary.complete ? 'Complete acceptance validation' : 'Partial or dry-run validation — not a sync/archive gate'}; ` +
    `${summary.sourceOnly ? 'source-of-truth only' : 'effective specification'}; ${summary.assigned} assigned scenarios.</p>` +
    `<p>Every effective scenario is assigned to exactly one group. Unexecuted assigned cases are incomplete coverage, not silently passed or superseded/skipped cases.</p>` +
    `<table><thead><tr><th>Group</th><th>Status</th><th>Assigned</th><th>Reported</th><th>Passed</th><th>Wall time</th><th>Evidence</th></tr></thead><tbody>${rows}</tbody></table>` +
    `<h2>Assignments</h2><ul>${summary.assignments.map(entry => `<li>${escapeHtml(entry.group)} — ${escapeHtml(entry.capability)} / ${escapeHtml(entry.requirement)} / ${escapeHtml(entry.name)}</li>`).join('')}</ul>` +
    `${summary.error ? `<p><strong>Failure:</strong> ${escapeHtml(summary.error)}</p>` : ''}</body></html>`;
}

async function runGate(options = {}, executeGroup = executeCucumber) {
  const start = process.hrtime.bigint();
  const prefix = options.prefix || (options.sourceOnly ? 'cucumber-specs' : 'cucumber');
  const reportRoot = path.join(acceptanceRoot, 'reports');
  fs.mkdirSync(reportRoot, { recursive: true });
  const fixtureExtraction = options.specRoot ? fs.mkdtempSync(path.join(os.tmpdir(), 'sdd-acceptance-extract-')) : undefined;
  const inventory = discover({ sourceOnly: options.sourceOnly, specRoot: options.specRoot,
    ...(fixtureExtraction ? { extractedRoot: path.join(fixtureExtraction, '.extracted') } : {}) });
  const filters = (options.names || []).map(name => new RegExp(name));
  const entries = inventory.entries.filter(entry => !filters.length || filters.some(filter => filter.test(entry.name)));
  if (!entries.length) throw new Error('No acceptance scenario matches the requested selection');
  const partial = Boolean(options.group || filters.length);
  const assignments = entries.filter(entry => !options.group || entry.group === options.group);
  if (!assignments.length) {
    if (fixtureExtraction) fs.rmSync(fixtureExtraction, { recursive: true, force: true });
    throw new Error('No acceptance scenario matches the selected group');
  }
  const manifest = { ...inventory, entries: assignments, complete: !partial, dryRun: Boolean(options.dryRun) };
  const manifestPath = path.join(reportRoot, `${prefix}-manifest.json`);
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  const summary = { version: 1, complete: !partial && !options.dryRun, dryRun: Boolean(options.dryRun),
    sourceOnly: Boolean(options.sourceOnly), specRoot: inventory.specRoot, fingerprint: inventory.fingerprint,
    assigned: assignments.length, assignments: assignments.map(({ id, capability, requirement, name, group }) => ({ id, capability, requirement, name, group })),
    status: 'running', groups: [] };
  const allFeatures = [];
  let aborted = false;
  let activeGroup;
  console.log(`[acceptance-gate] ${partial ? 'PARTIAL validation' : options.dryRun ? 'DRY RUN — no acceptance execution' : 'COMPLETE acceptance gate'}; freshly assigned ${assignments.length} scenarios`);
  try {
    for (const group of ['normal', 'lifecycle']) {
      const selected = assignments.filter(entry => entry.group === group);
      if (!selected.length) continue;
      console.log(`[acceptance-gate] ${group}: ${selected.length} assigned scenario(s)`);
      if (aborted) {
        summary.groups.push({ group, assigned: selected.length, status: 'not-run-after-failure', missing: selected.map(entry => entry.id) });
        continue;
      }
      const reports = { json: path.join(reportRoot, `${prefix}-${group}.json`),
        html: path.join(reportRoot, `${prefix}-${group}.html`), events: path.join(reportRoot, `${prefix}-${group}-events.ndjson`) };
      for (const file of [reports.json, reports.html]) fs.rmSync(file, { force: true });
      fs.writeFileSync(reports.events, '');
      activeGroup = group;
      const result = await executeGroup({ group, manifestPath, reports, dryRun: options.dryRun,
        paths: groupPaths(assignments, group), entries: selected });
      allFeatures.push(...result.features);
      const audit = auditGroup(selected, result.features, { dryRun: options.dryRun });
      const success = result.code === 0 && audit.allPassed;
      summary.groups.push({ group, ...audit, code: result.code, signal: result.signal,
        wallSeconds: result.wallSeconds, status: success ? (options.dryRun ? 'dry-run' : 'passed') : 'failed', report: reports.html });
      activeGroup = undefined;
      if (!success) aborted = true;
      // The normal runner has exited and its AfterAll teardown/audit has finished
      // before the dedicated runner can even be spawned.
    }
    const finalInventory = discover({ sourceOnly: options.sourceOnly, specRoot: options.specRoot, extractedRoot: inventory.extractedRoot });
    if (finalInventory.fingerprint !== inventory.fingerprint) throw new Error('Acceptance specification changed during validation; discovery is incomplete');
    summary.status = aborted ? 'failed' : options.dryRun ? 'dry-run' : partial ? 'partial-pass' : 'passed';
  } catch (error) {
    summary.status = 'failed';
    summary.error = error.message;
  } finally {
    for (const group of ['normal', 'lifecycle']) {
      const selected = assignments.filter(entry => entry.group === group);
      if (selected.length && !summary.groups.some(result => result.group === group)) {
        summary.groups.push({ group, assigned: selected.length, reported: 0, passed: 0,
          status: group === activeGroup ? 'failed' : 'not-run-after-failure', missing: selected.map(entry => entry.id) });
      }
    }
    summary.wallSeconds = Number(process.hrtime.bigint() - start) / 1e9;
    fs.writeFileSync(path.join(reportRoot, `${prefix}-summary.json`), JSON.stringify(summary, null, 2));
    fs.writeFileSync(path.join(reportRoot, `${prefix}-results.json`), JSON.stringify(allFeatures, null, 2));
    fs.writeFileSync(path.join(reportRoot, `${prefix}-report.html`), htmlReport(summary));
    for (const format of options.formats || []) {
      if (format.startsWith('json:')) fs.writeFileSync(path.resolve(acceptanceRoot, format.slice(5)), JSON.stringify(allFeatures, null, 2));
      else if (format.startsWith('html:')) fs.writeFileSync(path.resolve(acceptanceRoot, format.slice(5)), htmlReport(summary));
    }
    if (fixtureExtraction) fs.rmSync(fixtureExtraction, { recursive: true, force: true });
  }
  console.log(`[acceptance-gate] ${summary.status}; ${summary.wallSeconds.toFixed(2)}s; ${prefix}-report.html`);
  return summary;
}

module.exports = { auditGroup, htmlReport, parseArguments, readScenarios, runGate };
if (require.main === module) {
  runGate(parseArguments(process.argv.slice(2))).then(summary => {
    process.exitCode = summary.status === 'failed' ? 1 : 0;
  }).catch(error => { console.error(`[acceptance-gate] ${error.message}`); process.exitCode = 1; });
}
