'use strict';

const { Before, After, AfterAll, setDefaultTimeout } = require('@cucumber/cucumber');
const activeWorlds = new Set();
let cancelled = false;
let cancellationCleanup;

setDefaultTimeout(900_000);

// No BeforeAll, browser, normal World or application stack in this group. Each
// real invocation is owned by a serial child and is audited before the next one.
Before(function ({ pickle }) {
  if (cancelled) throw new Error('Lifecycle validation has been cancelled; no later scenario may start');
  this.scenarioName = pickle.name;
  activeWorlds.add(this);
});

After({ timeout: 900_000 }, async function () {
  try {
    await this.dispose();
  } finally {
    const audit = this.lifecyclePage.publishAudit();
    await this.attach(JSON.stringify(audit, null, 2), 'application/json');
    activeWorlds.delete(this);
  }
});

AfterAll({ timeout: 900_000 }, async function () {
  if (cancellationCleanup) await cancellationCleanup;
  const failures = [];
  for (const world of activeWorlds) {
    try { await world.dispose(); } catch (error) { failures.push(error); }
  }
  activeWorlds.clear();
  if (failures.length) throw new AggregateError(failures, 'Dedicated lifecycle final cleanup failed');
});

for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
  if (cancelled) return;
  cancelled = true;
  // Cucumber may stop execution, but it must not abandon an isolated child.
  cancellationCleanup = Promise.allSettled([...activeWorlds].map(world => world.dispose())).then(results => {
    process.exitCode = signal === 'SIGINT' ? 130 : 143;
    if (results.some(result => result.status === 'rejected')) throw new Error('Cancelled lifecycle cleanup failed');
  });
  cancellationCleanup.catch(() => { process.exitCode = 1; });
});
