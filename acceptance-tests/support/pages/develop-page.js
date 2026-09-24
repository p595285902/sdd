const { expect } = require('@playwright/test');

class DevelopPage {
  constructor(world) {
    this.world = world;
  }

  get page() {
    return this.world.page;
  }

  async authenticate(token) {
    await this.page.addInitScript((accessToken) => {
      localStorage.setItem('access_token', accessToken);
    }, token);
  }

  async openApplication(token) {
    await this.authenticate(token);
    await this.page.goto('/');
  }

  async selectDevelop() {
    await this.page.getByRole('link', { name: 'Develop' }).click();
  }

  async expectWorkspaceVisible() {
    await expect(this.page).toHaveURL(/\/develop$/);
    await expect(
      this.page.getByRole('heading', { name: 'Develop', exact: true }),
    ).toBeVisible();
  }
}

module.exports = { DevelopPage };