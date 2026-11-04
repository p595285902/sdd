'use strict';

const { setWorldConstructor, World } = require('@cucumber/cucumber');
const { AcceptanceLifecyclePage } = require('../../support/pages/acceptance-lifecycle-page.js');
const { AcceptanceGatePage } = require('../../support/pages/acceptance-gate-page.js');

class AcceptanceLifecycleWorld extends World {
  constructor(options) {
    super(options);
    this.lifecyclePage = new AcceptanceLifecyclePage(this);
    this.gatePage = new AcceptanceGatePage(this);
  }

  async dispose() {
    // Always audit real child ownership even if command validation cleanup fails.
    try { await this.gatePage.dispose?.(); }
    finally { await this.lifecyclePage.dispose(); }
  }
}

setWorldConstructor(AcceptanceLifecycleWorld);
module.exports = { AcceptanceLifecycleWorld };
