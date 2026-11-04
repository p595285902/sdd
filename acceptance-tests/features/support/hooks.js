const { chromium } = require('@playwright/test');
const { After, AfterAll, Before, BeforeAll, Status, setDefaultTimeout } = require('@cucumber/cucumber');
const { record, resetScenarioState, showApplicationLogs, startApplication, state, stopApplication } = require('./app-lifecycle.js');

let browser;
let cancellation;
let cancelHandlers;
setDefaultTimeout(90_000);

BeforeAll({ timeout: 300_000 }, async function () {
  let startup;
  const cancel = signal => {
    if (cancellation) return;
    record('cancelled', { signal });
    state.fatal = new Error('Acceptance invocation cancelled');
    cancellation = (async () => {
      // Do not tear down resources concurrently with an in-flight startup that
      // could create them again. The handlers cover startup as well as scenarios.
      await startup?.catch(() => {});
      state.fatal = new Error('Acceptance invocation cancelled');
      try { await browser?.close(); } finally { await stopApplication(); }
      process.exitCode = 128 + (signal === 'SIGINT' ? 2 : 15);
    })();
    cancellation.catch(error => { console.error(error.message); process.exitCode = 1; });
  };
  cancelHandlers = { SIGINT: () => cancel('SIGINT'), SIGTERM: () => cancel('SIGTERM') };
  for (const [signal, handler] of Object.entries(cancelHandlers)) process.on(signal, handler);
  startup = (async () => {
    await startApplication();
    if (cancellation) throw new Error('Acceptance startup cancelled');
    browser = await chromium.launch({ headless: !process.env.PWDEBUG, slowMo: process.env.PWDEBUG ? 1000 : 0 });
    if (cancellation) throw new Error('Acceptance browser startup cancelled');
  })();
  await startup;
});

Before(async function ({ pickle }) {
  this.scenarioName = pickle.name;
  await resetScenarioState();
  await this.replaceContexts(browser);
  this.scenarioStarted = true;
  record('scenario-start', { scenario: pickle.name, generation: state.generation });
});

After(async function ({ result }) {
  try {
    if (result?.status === Status.FAILED) await showApplicationLogs();
  } finally {
    await this.dispose();
    if (this.scenarioStarted) record('scenario-end', { scenario: this.scenarioName, status: result?.status });
  }
});

AfterAll({ timeout: 180_000 }, async function () {
  try {
    if (cancellation) await cancellation;
    else { try { await browser?.close(); } finally { await stopApplication(); } }
  } finally {
    for (const [signal, handler] of Object.entries(cancelHandlers || {})) process.removeListener(signal, handler);
  }
});
