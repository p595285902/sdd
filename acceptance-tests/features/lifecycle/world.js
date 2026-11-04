'use strict';

const { setWorldConstructor, World } = require('@cucumber/cucumber');
const { AcceptanceLifecyclePage } = require('../../support/pages/acceptance-lifecycle-page.js');

class AcceptanceLifecycleWorld extends World {
  constructor(options) {
    super(options);
    this.lifecyclePage = new AcceptanceLifecyclePage(this);
  }

  async dispose() {
    await this.lifecyclePage.dispose();
  }
}

setWorldConstructor(AcceptanceLifecycleWorld);
module.exports = { AcceptanceLifecycleWorld };
