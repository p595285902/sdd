'use strict';

const assert = require('node:assert/strict');
const { execFile, fork } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { state: parentState } = require('../../features/support/app-lifecycle.js');
const childPath = path.resolve(__dirname, '../../features/lifecycle/child-stack.cjs');
const repoRoot = path.resolve(__dirname, '../../..');
let activeInvocation;
const privateCredentials = new WeakMap();

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  promise.catch(() => {});
  return { promise, resolve, reject };
}

function dockerOutput(args) {
  return new Promise((resolve, reject) => execFile('docker', args, {
    cwd: repoRoot, timeout: 30_000, maxBuffer: 10 * 1024 * 1024,
  }, (error, stdout) => error ? reject(new Error('Lifecycle owned-resource Docker operation failed')) : resolve(stdout)));
}

function redact(text, secrets) {
  let result = String(text);
  for (const secret of secrets) if (secret) result = result.split(secret).join('[REDACTED]');
  return result;
}

class ChildInvocation {
  constructor(kind, forkProcess = fork) {
    assert.equal(activeInvocation, undefined, 'Lifecycle invocations must execute one at a time');
    assert.equal(parentState.stopped, true, 'The dedicated lifecycle parent must not own a normal-suite stack');
    this.kind = kind;
    this.ready = deferred();
    this.done = deferred();
    this.output = [];
    this.outputBytes = 0;
    this.publicMessages = [];
    privateCredentials.set(this, []);
    this.child = forkProcess(childPath, [], { cwd: repoRoot, stdio: ['ignore', 'pipe', 'pipe', 'ipc'],
      env: Object.fromEntries(Object.entries(process.env).filter(([key]) => ![
        'ACCEPTANCE_EVENT_LOG', 'ACCEPTANCE_RESET_TOKEN', 'ACCEPTANCE_RUN_ID', 'ACCEPTANCE_MANIFEST_PATH',
      ].includes(key))) });
    activeInvocation = this;
    const collect = chunk => {
      this.outputBytes += chunk.length;
      // Do not truncate: a truncated capture could hide a leaked credential.
      if (this.outputBytes > 20 * 1024 * 1024) this.transportError = 'Lifecycle child log exceeded its audit limit';
      else this.output.push(Buffer.from(chunk));
    };
    this.child.stdout.on('data', collect);
    this.child.stderr.on('data', collect);
    this.child.on('message', message => {
      if (message.type === 'private-credential') {
        privateCredentials.get(this).push(message.credential);
        return; // Never place the private message in reports, events or the World.
      }
      this.publicMessages.push(message);
      if (message.type === 'ready') {
        this.project = message.ready.project;
        this.ready.resolve(message.ready);
      }
      if (message.type === 'result') this.result = message.result;
    });
    this.child.once('error', () => {
      this.transportError = 'Lifecycle child could not be launched';
      this.ready.reject(new Error(this.transportError));
    });
    this.child.once('close', (code, signal) => {
      clearTimeout(this.startTimer);
      clearTimeout(this.totalTimer);
      if (activeInvocation === this) activeInvocation = undefined;
      this.closed = true;
      const secrets = privateCredentials.get(this);
      const raw = Buffer.concat(this.output).toString('utf8');
      const publicOutput = JSON.stringify(this.publicMessages);
      this.output = [];
      let error = this.transportError;
      if (!this.result || !secrets.length) error ||= 'Lifecycle child exited without a complete private/public audit';
      if (secrets.some(secret => raw.includes(secret) || publicOutput.includes(secret))) {
        error ||= 'Lifecycle child disclosed a run credential in its stdout, events or result';
      }
      const safeResult = JSON.parse(redact(JSON.stringify(this.result || {}), secrets));
      const audited = { ...safeResult, code, signal, logs: redact(raw, secrets),
        credentialsRedacted: !error, ...(error ? { auditError: error } : {}) };
      this.audited = audited;
      if (!this.project) this.project = this.result?.project;
      this.ready.reject(new Error(error || 'Lifecycle invocation exited before reporting readiness'));
      this.done.resolve(audited);
    });
    this.startTimer = setTimeout(() => {
      this.transportError = 'Lifecycle child exceeded its startup deadline';
      this.ready.reject(new Error(this.transportError));
      this.child.kill('SIGTERM');
    }, 360_000);
    this.totalTimer = setTimeout(() => {
      this.transportError = 'Lifecycle child exceeded its invocation deadline';
      this.child.kill('SIGTERM'); // Never use SIGKILL and abandon owned resources.
    }, 600_000);
    this.send('start', { kind });
  }

  send(command, details = {}) {
    if (!this.child.connected) return;
    this.child.send({ command, id: randomUUID(), ...details }, error => {
      if (error) this.transportError = 'Lifecycle child IPC command failed';
    });
  }

  async started() {
    const ready = await this.ready.promise;
    clearTimeout(this.startTimer);
    return ready;
  }

  async execute() {
    await this.started();
    this.send('execute');
    return this.done.promise;
  }

  async cancel(signal = 'SIGTERM') {
    if (!this.closed) this.child.kill(signal);
    return this.done.promise;
  }

  async dispose() {
    if (!this.closed) this.send('stop');
    return this.done.promise;
  }
}

class AcceptanceLifecyclePage {
  constructor(world, options = {}) {
    this.world = world;
    this.docker = options.dockerOutput || dockerOutput;
    this.forkProcess = options.forkProcess || fork;
    this.invocations = [];
    this.results = [];
    this.sentinel = undefined;
  }

  async independentValidation() {
    assert.equal(Boolean(this.disposal), false, 'Disposed lifecycle validation cannot start another invocation');
    assert.equal(parentState.stopped, true, 'Lifecycle validation must not run inside a live normal stack');
    assert.equal(activeInvocation, undefined, 'Another lifecycle invocation is still active');
    await this.createUnrelatedSentinel();
  }

  async createUnrelatedSentinel() {
    if (this.sentinel) return;
    const project = `sdd-lifecycle-sentinel-${randomUUID()}`;
    const labels = ['--label', `com.docker.compose.project=${project}`,
      '--label', `sdd.preview.project=${project}`, '--label', `sdd.preview.chat-id=${randomUUID()}`];
    this.sentinel = { project, labels };
    // Register each identifier immediately. Cleanup addresses only resources
    // created here; no global prune, project-prefix deletion or pre-existing IDs.
    this.sentinel.network = (await this.docker(['network', 'create', '--internal', ...labels, `${project}-network`])).trim();
    this.sentinel.volume = (await this.docker(['volume', 'create', ...labels, `${project}-volume`])).trim();
    this.sentinel.snapshot = await this.sentinelSnapshot();
  }

  async addSentinelContainer() {
    if (!this.sentinel || this.sentinel.container) return;
    const { project, labels, network, volume } = this.sentinel;
    // The invocation has now pulled postgres:18. This container never executes
    // application code and is unrelated to the acceptance project's resources.
    this.sentinel.container = (await this.docker(['create', ...labels, '--name', `${project}-container`,
      '--network', network, '--mount', `type=volume,source=${volume},target=/var/lib/postgresql`, 'postgres:18'])).trim();
    this.sentinel.snapshot = await this.sentinelSnapshot();
  }

  async sentinelSnapshot() {
    const snapshot = {};
    for (const [kind, args] of [['container', ['inspect']], ['network', ['network', 'inspect']], ['volume', ['volume', 'inspect']]]) {
      if (!this.sentinel[kind]) continue;
      snapshot[kind] = JSON.parse(await this.docker([...args, this.sentinel[kind]]));
      if (kind === 'container') {
        for (const container of snapshot[kind]) {
          if (container.Mounts) container.Mounts.sort((a, b) => a.Destination.localeCompare(b.Destination));
        }
      }
    }
    return snapshot;
  }

  async startExecutionInvocation() {
    await this.startIsolated(this.world.scenarioName === 'Controlled cancellation removes the owned stack' ? 'cancellation' : 'failure');
  }

  async startIsolated(kind = 'failure') {
    await this.independentValidation();
    this.current = new ChildInvocation(kind, this.forkProcess);
    this.invocations.push(this.current);
    await this.current.started();
    assert.equal(Boolean(this.disposal), false, 'Cancelled lifecycle validation cannot create later fixtures');
    await this.addSentinelContainer();
  }

  async twoSerialInvocations() {
    await this.independentValidation();
    for (let index = 0; index < 2; index++) {
      await this.startIsolated('completed');
      await this.collect(await this.current.execute());
      // This is deliberately before launching the next child, not an eventual
      // After hook: there must be no overlap or retained reusable stack.
      await this.assertResultCleanup(this.results.at(-1));
      await this.unrelatedUnchanged();
    }
  }

  async collect(result) {
    if (!this.results.includes(result)) this.results.push(result);
    assert.equal(result.auditError, undefined, result.auditError || 'Lifecycle log audit failed');
    assert.equal(result.credentialsRedacted, true, 'Lifecycle stdout/events/report credential audit failed');
    assert.equal(result.cleanupVerified, true, 'Child did not complete owned-resource teardown');
    return result;
  }

  async failInvocation() {
    if (!this.current) await this.startIsolated('failure');
    const result = await this.collect(await this.current.execute());
    assert.equal(result.outcome, 'failed');
    assert.equal(result.code, 1, 'Intentionally failed child invocation did not fail');
  }

  async cancelInvocation() {
    if (!this.current) await this.startIsolated('cancellation');
    const result = await this.collect(await this.current.cancel('SIGTERM'));
    assert.equal(result.outcome, 'cancelled');
    assert.equal(result.code, 143);
    assert.ok(result.events.some(event => event.type === 'invocation-cancelled' && event.signal === 'SIGTERM'));
  }

  async requestOutsideControls() {
    await this.collect(await this.current.execute());
  }

  async requestTerminalReset() {
    const variants = this.current.kind === 'cleanup' ? ['cleanup', 'filesystem', 'partial-controller'] : [this.current.kind];
    for (const [index, kind] of variants.entries()) {
      if (index) await this.startIsolated(kind);
      const result = await this.collect(await this.current.execute());
      assert.equal(result.outcome, 'reset-failed');
      assert.equal(result.code, 1);
      this.failedBoundary();
      this.singleStartup();
      await this.assertResultCleanup(result);
      await this.unrelatedUnchanged();
    }
  }

  distinctProjects() {
    assert.equal(this.results.length, 2);
    assert.notEqual(this.results[0].project, this.results[1].project);
    for (const result of this.results) assert.equal(result.code, 0);
  }

  async assertResultCleanup(result) {
    assert.equal(result.cleanupVerified, true);
    const stopped = result.events.filter(event => event.type === 'stack-stopped');
    assert.equal(stopped.length, 1);
    assert.equal(stopped[0].ownedResourcesEmpty, true);
    for (const label of ['com.docker.compose.project', 'sdd.preview.project']) {
      for (const [resource, args] of [['containers', ['ps', '-aq']], ['networks', ['network', 'ls', '-q']],
        ['volumes', ['volume', 'ls', '-q']]]) {
        assert.equal((await this.docker([...args, '--filter', `label=${label}=${result.project}`])).trim(), '',
          `Owned lifecycle ${resource} survived final teardown`);
      }
    }
    // Preview images are part of final cleanup too; immutable stack build images
    // do not carry the chat-preview ownership label and are not targeted.
    assert.equal((await this.docker(['image', 'ls', '-q', '--filter', `label=sdd.preview.project=${result.project}`])).trim(), '');
  }

  async ownedResourcesRemoved() {
    assert.ok(this.results.length, 'No invocation was actually executed');
    for (const result of this.results) await this.assertResultCleanup(result);
  }

  async unrelatedUnchanged() {
    assert.ok(this.sentinel?.snapshot, 'No fixture-owned unrelated sentinel was established');
    assert.deepEqual(await this.sentinelSnapshot(), this.sentinel.snapshot,
      'Lifecycle invocation modified unrelated project resources');
  }

  singleStartup() {
    for (const result of this.results) {
      assert.equal(result.events.filter(event => event.type === 'stack-start').length, 1);
      assert.equal(result.events.filter(event => event.type === 'stack-ready').length, 1);
    }
  }

  failedBoundary() {
    const result = this.results.at(-1);
    assert.equal(result.diagnostics.reset.phase, 'failed');
    assert.equal(result.diagnostics.reset.baseline_verified, false);
    assert.equal(result.events.filter(event => event.type === 'scenario-start').length, 1);
    assert.equal(result.events.some(event => event.type === 'scenario-start' && event.name === 'later'), false);
    assert.ok(result.events.some(event => event.type === 'scenario-blocked' && event.name === 'later'));
    assert.equal(result.diagnostics.admissionStatus, 503);
    assert.equal(result.credentialsRedacted, true);
    const failure = result.events.find(event => event.type === 'reset-failed');
    assert.ok(failure, 'Runner did not report its terminal failed phase');
    assert.equal(failure.phase, result.diagnostics.reset.failure_phase);
    assert.ok(result.logs.includes('reset-failed'), 'Credential-redacted logs omitted failed reset phase');
  }

  deadlineFailed() {
    this.failedBoundary();
    const result = this.results.at(-1);
    assert.equal(result.diagnostics.reset.failure_phase, 'quiescing');
    assert.ok(Object.values(result.diagnostics.blockedWork).some(count => count > 0));
    assert.ok(result.events.some(event => event.type === 'lifecycle-lock-released'));
  }

  cleanupFailed() {
    assert.deepEqual(this.results.map(result => result.kind), ['cleanup', 'filesystem', 'partial-controller']);
    for (const result of this.results) {
      assert.equal(result.diagnostics.reset.phase, 'failed');
      assert.equal(result.diagnostics.reset.baseline_verified, false);
      assert.equal(result.diagnostics.reset.failure_phase, result.kind === 'filesystem' ? 'cleaning_files' : 'cleaning_previews');
      if (result.kind === 'cleanup') assert.ok(result.diagnostics.refusedFixtureUnchanged);
      else assert.ok(result.diagnostics.partialCleanup, 'Real partial deletion was not observed');
      assert.equal(result.diagnostics.admissionStatus, 503);
      assert.equal(result.events.filter(event => event.type === 'scenario-start').length, 1);
    }
  }

  controlsUnavailable() {
    const controls = this.results.at(-1).diagnostics.controls;
    assert.equal(controls.responses.length, 3);
    assert.equal(controls.controller.length, 4);
    assert.ok([...controls.responses, ...controls.controller].every(response => response.status === 404));
  }

  outsideStateUnchanged() {
    assert.equal(this.results.at(-1).diagnostics.controls.unchanged, true);
  }

  async cancelledCleanup() {
    assert.equal(this.results.at(-1).outcome, 'cancelled');
    await this.ownedResourcesRemoved();
  }

  async failedCleanup() {
    assert.equal(this.results.at(-1).code, 1);
    this.singleStartup();
    await this.ownedResourcesRemoved();
    await this.unrelatedUnchanged();
  }

  // The legacy source-only wording describes the same fresh-run lifecycle.
  // Its dedicated parent intentionally has no extra live normal-suite stack.
  async legacyFreshRun() { await this.startIsolated('completed'); }
  async legacyScenariosFinish() { await this.collect(await this.current.execute()); }
  async legacyOnlyOwnedRemoved() { await this.ownedResourcesRemoved(); await this.unrelatedUnchanged(); }
  async legacyNextFreshRun() {
    await this.startIsolated('completed');
    await this.collect(await this.current.execute());
    this.distinctProjects();
    await this.ownedResourcesRemoved();
    await this.unrelatedUnchanged();
  }

  report() {
    return { group: 'lifecycle', parentOwnsStack: false,
      invocations: this.results.map(result => ({ project: result.project, kind: result.kind,
        outcome: result.outcome, code: result.code, cleanupVerified: result.cleanupVerified,
        credentialsRedacted: result.credentialsRedacted, events: result.events,
        failurePhase: result.diagnostics?.reset?.failure_phase, logs: result.logs })) };
  }

  publishAudit() {
    const report = this.report();
    if (this.auditPublished) return report;
    this.auditPublished = true;
    for (const invocation of report.invocations) {
      // Publish child timestamps only after the independent secret audit. The
      // complete gate can then prove normal teardown precedes real child starts
      // without allowing child stdout or direct event-file writes to bypass it.
      if (process.env.ACCEPTANCE_EVENT_LOG) {
        for (const childEvent of invocation.events) {
          fs.appendFileSync(process.env.ACCEPTANCE_EVENT_LOG,
            `${JSON.stringify({ ...childEvent, group: 'lifecycle' })}\n`);
        }
      }
      const event = { type: 'lifecycle-invocation-audited', at: Date.now(), group: 'lifecycle',
        project: invocation.project, outcome: invocation.outcome, code: invocation.code,
        cleanupVerified: invocation.cleanupVerified, credentialsRedacted: invocation.credentialsRedacted,
        ...(invocation.failurePhase ? { failurePhase: invocation.failurePhase } : {}) };
      const line = JSON.stringify(event);
      if (process.env.ACCEPTANCE_EVENT_LOG) fs.appendFileSync(process.env.ACCEPTANCE_EVENT_LOG, `${line}\n`);
      console.log(`[acceptance-lifecycle] ${line}`);
    }
    return report;
  }

  async dispose() {
    // Outer cancellation and Cucumber After may arrive together. They share one
    // cleanup transaction rather than racing deletion of the owned sentinel.
    this.disposal ||= this.disposeOwnedResources();
    return this.disposal;
  }

  async disposeOwnedResources() {
    const errors = [];
    for (const invocation of this.invocations) {
      try {
        const result = await invocation.dispose();
        await this.collect(result);
        await this.assertResultCleanup(result);
      } catch (error) { errors.push(error); }
    }
    if (this.sentinel) {
      try {
        if (this.sentinel.snapshot) await this.unrelatedUnchanged();
      } catch (error) { errors.push(error); }
      // IDs are obtained only from create calls above. Inspect labels before
      // removing anything; never clean by wildcard or touch a pre-existing ID.
      for (const [kind, inspect, remove] of [
        ['container', ['inspect'], ['rm', '-f']],
        ['network', ['network', 'inspect'], ['network', 'rm']],
        ['volume', ['volume', 'inspect'], ['volume', 'rm']],
      ]) {
        if (!this.sentinel[kind]) continue;
        try {
          const info = JSON.parse(await this.docker([...inspect, this.sentinel[kind]]))[0];
          const labels = kind === 'container' ? info.Config.Labels : info.Labels;
          assert.equal(labels['com.docker.compose.project'], this.sentinel.project);
          assert.equal(labels['sdd.preview.project'], this.sentinel.project);
          await this.docker([...remove, this.sentinel[kind]]);
          this.sentinel[kind] = undefined;
        } catch (error) { errors.push(error); }
      }
      for (const args of [['ps', '-aq'], ['network', 'ls', '-q'], ['volume', 'ls', '-q']]) {
        try {
          assert.equal((await this.docker([...args, '--filter', `label=com.docker.compose.project=${this.sentinel.project}`])).trim(), '',
            'Fixture-owned unrelated sentinel survived final cleanup');
        } catch (error) { errors.push(error); }
      }
      if (!errors.length) this.sentinel = undefined;
    }
    if (errors.length) throw new AggregateError(errors, 'Lifecycle final cleanup/audit failed');
  }
}

module.exports = { AcceptanceLifecyclePage, ChildInvocation, redact };
