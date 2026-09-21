const { request } = require('@playwright/test');
const { setWorldConstructor, World } = require('@cucumber/cucumber');

const { state } = require('./app-lifecycle.js');

class AcceptanceWorld extends World {
  async openApiContext(headers = {}) {
    if (this.api) await this.api.dispose();
    this.api = await request.newContext({
      baseURL: state.baseUrl,
      extraHTTPHeaders: headers,
    });
    return this.api;
  }

  async dispose() {
    await this.page?.close();
    await this.context?.close();
    await this.api?.dispose();
  }
}

setWorldConstructor(AcceptanceWorld);

module.exports = { AcceptanceWorld };