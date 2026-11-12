'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { generateMessages } = require('@cucumber/gherkin');
const { IdGenerator, SourceMediaType } = require('@cucumber/messages');
const { extractAll } = require('../extract-gherkin.cjs');

const acceptanceRoot = path.resolve(__dirname, '..');
const specRoot = path.resolve(acceptanceRoot, '../openspec');
const executionGroups = ['normal', 'lifecycle', 'preview-restart'];
const validationRequirements = new Set([
  'Fresh-run lifecycle remains unchanged',
  'Separate validation groups retain complete effective-spec coverage',
  'Unverified reset fails the invocation without a replacement stack',
]);

function executionGroup(capability, requirement, scenario) {
  // A real controller restart intentionally invalidates the process-local reset
  // identity. Run this one scenario in a fresh invocation, never repair/reseed
  // that identity or allow the shared normal runner to cross the failed boundary.
  if (capability === 'develop-preview-runtime' &&
      requirement === 'Sandbox cleanup preserves durable launch history' &&
      scenario === 'Controller restart reconciles a missing sandbox') return 'preview-restart';
  if ((capability === 'acceptance-stack-reuse' && validationRequirements.has(requirement)) ||
      (capability === 'acceptance-state-reset' &&
        (validationRequirements.has(requirement) || scenario === 'Reset controls are unavailable outside acceptance mode'))) {
    return 'lifecycle';
  }
  return 'normal';
}

// Reuse the unchanged, canonical composition binding for isolated inventories.
// Giving the byte-identical module its own directory changes only where it reads
// generated files; its supersession, conflict and exclusion semantics stay intact.
function composedPaths(extractedRoot) {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'sdd-acceptance-compose-'));
  const modulePath = path.join(temporary, 'openspec-effective-paths.cjs');
  try {
    fs.symlinkSync(extractedRoot, path.join(temporary, '.extracted'), 'dir');
    fs.symlinkSync(path.join(acceptanceRoot, 'node_modules'), path.join(temporary, 'node_modules'), 'dir');
    fs.copyFileSync(path.join(acceptanceRoot, 'openspec-effective-paths.cjs'), modulePath);
    return require(modulePath).effectivePaths().map(entry => {
      const [file, ...lines] = entry.split(':');
      return { file: path.join(extractedRoot, file.replace(/^\.extracted\//, '')), lines: new Set(lines.map(Number)) };
    });
  } finally {
    delete require.cache[modulePath];
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

function scenarioNodes(document) {
  const nodes = new Map();
  for (const child of document.feature?.children || []) {
    if (child.scenario) throw new Error('Acceptance scenarios must belong to a Requirement');
    if (!child.rule) continue;
    for (const ruleChild of child.rule.children) {
      if (!ruleChild.scenario) continue;
      const scenario = ruleChild.scenario;
      const details = { requirement: child.rule.name, scenario: scenario.name, line: scenario.location.line };
      nodes.set(scenario.id, details);
      for (const examples of scenario.examples || []) {
        for (const row of examples.tableBody || []) nodes.set(row.id, { ...details, line: row.location.line });
      }
    }
  }
  return nodes;
}

function discover(options = {}) {
  const root = path.resolve(options.specRoot || specRoot);
  const extractedRoot = path.resolve(options.extractedRoot || path.join(acceptanceRoot, '.extracted'));
  if (!fs.statSync(root).isDirectory()) throw new Error('Acceptance specification root is not a directory');
  const extraction = extractAll(root, extractedRoot);
  const selected = options.sourceOnly
    ? extraction.written.filter(file => path.relative(extractedRoot, file).startsWith('specs/')).map(file => ({ file, lines: new Set() }))
    : composedPaths(extractedRoot);
  const entries = [];
  const identities = new Set();
  const newId = IdGenerator.incrementing();
  for (const selection of selected) {
    const relative = path.relative(extractedRoot, selection.file).split(path.sep).join('/');
    if (relative.includes('changes/archive/') || relative.includes('changes/backlog/')) {
      throw new Error('Historical or backlog acceptance scenario reached discovery');
    }
    const capability = relative.slice(relative.lastIndexOf('specs/') + 6).replace(/\/spec\.feature$/, '');
    const source = fs.readFileSync(selection.file, 'utf8');
    const envelopes = generateMessages(source, selection.file, SourceMediaType.TEXT_X_CUCUMBER_GHERKIN_PLAIN,
      { includeGherkinDocument: true, includePickles: true, newId });
    const error = envelopes.find(envelope => envelope.parseError);
    if (error) throw new Error(`Invalid acceptance Gherkin: ${JSON.stringify(error.parseError)}`);
    const document = envelopes.find(envelope => envelope.gherkinDocument)?.gherkinDocument;
    if (!document?.feature) throw new Error(`No acceptance Feature in ${relative}`);
    const nodes = scenarioNodes(document);
    for (const { pickle } of envelopes.filter(envelope => envelope.pickle)) {
      const parent = pickle.astNodeIds.map(id => nodes.get(id)).filter(Boolean).at(-1);
      if (!parent) throw new Error(`Unclassified acceptance scenario: ${pickle.name}`);
      if (selection.lines.size && !selection.lines.has(parent.line) &&
          !pickle.astNodeIds.some(id => selection.lines.has(nodes.get(id)?.line))) continue;
      const id = JSON.stringify([capability, parent.requirement, parent.scenario, pickle.name,
        pickle.steps.map(step => step.text)]);
      if (identities.has(id)) throw new Error(`Duplicate effective acceptance scenario: ${pickle.name}`);
      identities.add(id);
      entries.push({ id, capability, requirement: parent.requirement, scenario: parent.scenario,
        name: pickle.name, line: parent.line, uri: selection.file,
        source: path.join(root, relative.replace(/\.feature$/, '.md')),
        group: executionGroup(capability, parent.requirement, parent.scenario),
        steps: pickle.steps.map(step => step.text) });
    }
  }
  if (!entries.length) throw new Error('Acceptance discovery produced an empty inventory');
  const fingerprint = createHash('sha256');
  for (const file of extraction.written.sort()) {
    fingerprint.update(path.relative(extractedRoot, file));
    fingerprint.update(fs.readFileSync(file));
  }
  return { version: 1, sourceOnly: Boolean(options.sourceOnly), specRoot: root, extractedRoot,
    fingerprint: fingerprint.digest('hex'), entries };
}

function groupPaths(entries, group) {
  const paths = new Map();
  for (const entry of entries.filter(item => item.group === group)) {
    if (!paths.has(entry.uri)) paths.set(entry.uri, new Set());
    paths.get(entry.uri).add(entry.line);
  }
  return [...paths].map(([file, lines]) => `${file}:${[...lines].sort((a, b) => a - b).join(':')}`);
}

module.exports = { acceptanceRoot, discover, executionGroup, executionGroups, groupPaths };
