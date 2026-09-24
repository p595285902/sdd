const { chromium } = require('@playwright/test');
const {
  After,
  AfterAll,
  Before,
  BeforeAll,
  setDefaultTimeout,
} = require('@cucumber/cucumber');

const { startApplication, state, stopApplication } = require('./app-lifecycle.js');

let browser;

setDefaultTimeout(60_000);

BeforeAll({ timeout: 300_000 }, async function () {
  await startApplication();
  browser = await chromium.launch({
    headless: !process.env.PWDEBUG,
    slowMo: process.env.PWDEBUG ? 1000 : 0
  });
});

Before(async function () {
  this.context = await browser.newContext({ baseURL: state.baseUrl });
  this.page = await this.context.newPage();
});

After(async function () {
  await this.dispose();
});

AfterAll({ timeout: 120_000 }, async function () {
  await browser?.close();
  await stopApplication();
});