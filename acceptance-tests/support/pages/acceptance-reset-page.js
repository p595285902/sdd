'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const lifecycle = require('../../features/support/app-lifecycle.js');

// Only the self-contained command fixtures use this page; normal scenario reset
// remains in the shared lifecycle hooks.
class AcceptanceResetPage {
  constructor(world) { this.world = world; }
  get api() { return this.world.apiClient; }
  async reset() {
    this.previousContext = this.world.context;
    this.previousRequests = [...this.world.apiContexts];
    await lifecycle.resetScenarioState();
    await this.world.replaceContexts();
  }
  async expectFreshContexts() {
    assert.notEqual(this.world.context, this.previousContext);
    assert.equal(this.world.page.context(), this.world.context);
    assert.ok(this.previousContext.pages().length === 0);
    for (const api of this.previousRequests) await assert.rejects(api.get('/api/v1/utils/health-check/'));
    await lifecycle.verifyStack();
  }
  async armNextBoundaryFailure() {
    const manifest = JSON.parse(fs.readFileSync(process.env.ACCEPTANCE_MANIFEST_PATH, 'utf8'));
    const root = fs.realpathSync(manifest.specRoot);
    assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir()));
    assert.ok(path.basename(root).startsWith('sdd-gate-fixture-'), 'Faults require an owned isolated command fixture');
    assert.ok(manifest.entries.some(entry => entry.steps.includes('the isolated command fixture arms a bounded filesystem cleanup fault')));
    const { createFilesystemCleanupFault } = require('../acceptance-cleanup-fixtures.cjs');
    await createFilesystemCleanupFault();
    lifecycle.record('command-boundary-fixture', { generation: lifecycle.state.generation });
  }
  async configuredRepository() {
    await lifecycle.configureDemoRepository(true);
    this.identity = await lifecycle.verifyStack();
    this.initialBackend = await lifecycle.backendInfo();
    assert.equal(this.initialBackend.healthy, true);
  }
  async sameRepositoryRequests() {
    await lifecycle.configureDemoRepository(true);
    await this.api.configureFakeLlm([{ kind: 'text', text: 'previous configuration scenario reply' }]);
    await this.reset();
    await lifecycle.configureDemoRepository(true);
  }
  async expectNoRecreation() { await this.expectSameStack(); assert.equal(lifecycle.state.backendRecreations, 0); }
  async expectIndependentState() {
    await this.expectFreshContexts();
    assert.deepEqual(await this.api.fakeLlmRequests(), []);
    const api = await this.world.openApiContext();
    assert.equal((await api.post('/api/v1/testing/llm/v1/responses', { data: { input: [] } })).status(), 500);
  }
  async expectUnavailableRepository() {
    const info = await lifecycle.backendInfo();
    assert.equal(info.repo, '');
    assert.equal(info.healthy, true);
    assert.equal(info.id, this.initialBackend.id);
    await lifecycle.verifyStack();
  }
  async expectSameStack() { assert.deepEqual(await lifecycle.verifyStack(), this.identity); }
}
module.exports = { AcceptanceResetPage };
