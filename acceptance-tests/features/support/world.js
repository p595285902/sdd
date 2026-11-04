const { request } = require('@playwright/test');
const { setWorldConstructor, World } = require('@cucumber/cucumber');

const { state } = require('./app-lifecycle.js');
const { ApiClient } = require('../../support/api-client.js');
const { AdminUsersPage } = require('../../support/pages/admin-users-page.js');
const { DevelopPage } = require('../../support/pages/develop-page.js');
const { PreviewWorkloadPage } = require('../../support/pages/preview-workload-page.js');
const { AcceptanceResetPage } = require('../../support/pages/acceptance-reset-page.js');

class AcceptanceWorld extends World {
  constructor(options) {
    super(options);
    this.apiContexts = [];
    this.applicationState = state;
    this.apiClient = new ApiClient(this);
    this.adminUsersPage = new AdminUsersPage(this);
    this.developPage = new DevelopPage(this);
    this.previewWorkloadPage = new PreviewWorkloadPage(this);
    this.resetPage = new AcceptanceResetPage(this);
  }

  async openApiContext(headers = {}) {
    const api = await request.newContext({
      baseURL: state.baseUrl,
      extraHTTPHeaders: headers,
    });
    this.apiContexts.push(api);
    return api;
  }

  async replaceContexts(browser = this.context?.browser()) {
    await this.disposeContexts();
    this.apiClient = new ApiClient(this);
    this.previewWorkloadPage.chatIds = [];
    this.context = await browser.newContext({ baseURL: state.baseUrl });
    this.page = await this.context.newPage();
  }

  async disposeContexts() {
    const results = await Promise.allSettled([
      this.context?.close(), ...this.apiContexts.map(api => api.dispose()),
    ]);
    this.apiContexts = [];
    this.page = undefined;
    this.context = undefined;
    const failed = results.find(result => result.status === 'rejected');
    if (failed) throw failed.reason;
  }

  async dispose() {
    try {
      if (!state.fatal) await this.previewWorkloadPage.stopAll();
    } finally {
      await this.disposeContexts();
    }
  }
}

setWorldConstructor(AcceptanceWorld);

module.exports = { AcceptanceWorld };