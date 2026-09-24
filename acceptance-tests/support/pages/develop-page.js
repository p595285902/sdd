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

  async visibleChatTitles(expectedCount) {
    const chatButtons = this.page
      .getByRole('navigation', { name: 'Development Chats' })
      .getByRole('button');
    if (expectedCount !== undefined) {
      await expect(chatButtons).toHaveCount(expectedCount);
    }
    return chatButtons.allTextContents();
  }

  async selectChat(title) {
    await this.page
      .getByRole('navigation', { name: 'Development Chats' })
      .getByRole('button', { name: title, exact: true })
      .click();
  }

  async renameSelectedChat(title) {
    await this.page.getByRole('button', { name: 'Rename Development Chat' }).click();
    await this.page.getByLabel('Development Chat title').fill(title);
    await this.page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(this.page.getByRole('heading', { name: title })).toBeVisible();
  }

  async loadOlderMessages() {
    await this.page.getByRole('button', { name: 'Load older messages' }).click();
  }

  async visibleMessageContents() {
    return this.page.locator('article').evaluateAll((messages) =>
      messages.map((message) =>
        message.textContent.replace(/^(user|assistant): /, ''),
      ),
    );
  }
}

module.exports = { DevelopPage };