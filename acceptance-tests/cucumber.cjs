'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { discover, executionGroup, groupPaths } = require('./support/acceptance-inventory.cjs');

let effective;
let sourceOnly;
if (process.env.ACCEPTANCE_MANIFEST_PATH) {
  effective = JSON.parse(fs.readFileSync(process.env.ACCEPTANCE_MANIFEST_PATH, 'utf8'));
  if (effective.version !== 1 || !Array.isArray(effective.entries) || !effective.entries.length ||
      new Set(effective.entries.map(entry => entry.id)).size !== effective.entries.length ||
      effective.entries.some(entry => executionGroup(entry.capability, entry.requirement, entry.scenario) !== entry.group)) {
    throw new Error('Invalid or duplicated acceptance group manifest');
  }
  sourceOnly = effective;
} else {
  effective = discover();
  sourceOnly = discover({ sourceOnly: true });
  console.error('[acceptance-gate] Direct Cucumber profiles are PARTIAL validation; npm test runs the complete gate.');
}

const normalSteps = fs.readdirSync(path.join(__dirname, 'step-definitions'))
  .filter(file => file.endsWith('.steps.js') && !['acceptance-lifecycle.steps.js', 'acceptance-gate.steps.js'].includes(file))
  .map(file => `step-definitions/${file}`);
function profile(inventory, group) {
  return { paths: groupPaths(inventory.entries, group), parallel: 0, retry: 0, failFast: true,
    import: group === 'normal' ? ['support/world.js', 'support/hooks.js', ...normalSteps]
      : ['features/lifecycle/world.js', 'features/lifecycle/hooks.js', 'step-definitions/acceptance-lifecycle.steps.js', 'step-definitions/acceptance-gate.steps.js'],
    format: ['progress-bar', ['html', `reports/cucumber-${group}.html`]] };
}

module.exports = { default: profile(effective, 'normal'), normal: profile(effective, 'normal'),
  lifecycle: profile(effective, 'lifecycle'), specs: profile(sourceOnly, 'normal'),
  specsNormal: profile(sourceOnly, 'normal'), specsLifecycle: profile(sourceOnly, 'lifecycle') };
