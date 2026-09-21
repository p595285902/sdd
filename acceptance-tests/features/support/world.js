const { request } = require('@playwright/test');
const { setWorldConstructor, World } = require('@cucumber/cucumber');

const { state } = require('./app-lifecycle.js');
const { ApiClient } = require('../../support/api-client.js');
const { AdminUsersPage } = require('../../support/pages/admin-users-page.js');

class AcceptanceWorld extends World {
  constructor(options) {
    super(options);
    this.apiContexts = [];
    this.applicationState = state;
    this.apiClient = new ApiClient(this);
    this.adminUsersPage = new AdminUsersPage(this);
  }

  async openApiContext(headers = {}) {
    const api = await request.newContext({
      baseURL: state.baseUrl,
      extraHTTPHeaders: headers,
    });
    this.apiContexts.push(api);
    return api;
  }

  async dispose() {
    await this.page?.close();
    await this.context?.close();
    await Promise.all(this.apiContexts.map((api) => api.dispose()));
  }
}

setWorldConstructor(AcceptanceWorld);

module.exports = { AcceptanceWorld };