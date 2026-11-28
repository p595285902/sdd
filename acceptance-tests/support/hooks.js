'use strict';

// Suite lifecycle: one stack and one headless Chromium per invocation, one
// fresh browser context per scenario (clean storage, serial execution).

const {
  After,
  AfterAll,
  Before,
  BeforeAll,
  setDefaultTimeout,
} = require('@cucumber/cucumber');
const { chromium } = require('@playwright/test');

const { getBaseUrl, start, stop } = require('./app-lifecycle');

const STACK_TIMEOUT_MS = 20 * 60 * 1000;
const SCENARIO_TIMEOUT_MS = 60 * 1000;

setDefaultTimeout(SCENARIO_TIMEOUT_MS);

let browser;

BeforeAll({ timeout: STACK_TIMEOUT_MS }, async function () {
  await start();
  browser = await chromium.launch({ headless: true });
});

Before(async function () {
  this.context = await browser.newContext({ baseURL: getBaseUrl() });
  this.page = await this.context.newPage();
});

After(async function () {
  if (this.context) await this.context.close();
});

AfterAll({ timeout: 5 * 60 * 1000 }, async function () {
  if (browser) {
    await browser.close();
    browser = undefined;
  }
  await stop();
});
