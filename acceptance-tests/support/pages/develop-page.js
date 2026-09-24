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

  async open(token) {
    await this.authenticate(token);
    await this.page.goto('/develop');
    await this.expectWorkspaceVisible();
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

  async startNewChat() {
    await this.page.getByRole('button', { name: 'New Development Chat' }).click();
  }

  async submitFirstMessage(content) {
    await this.page
      .getByRole('textbox', { name: 'First message', exact: true })
      .fill(content);
    await this.page.getByRole('button', { name: 'Send first message' }).click();
    await expect(this.page.getByRole('heading', { name: content })).toBeVisible();
  }

  async visibleChatTitles() {
    return this.page
      .getByRole('navigation', { name: 'Development Chats' })
      .getByRole('button')
      .allTextContents();
  }
}

module.exports = { DevelopPage };