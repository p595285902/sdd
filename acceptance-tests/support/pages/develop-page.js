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

  async setupSelectedDemoRepository() {
    await this.page
      .getByRole('button', { name: 'Set up demo repository' })
      .click();
    await expect(
      this.page.getByRole('button', { name: 'Demo repository ready' }),
    ).toBeDisabled();
  }

  async openDeleteConfirmation() {
    await this.page
      .getByRole('button', { name: 'Delete Development Chat' })
      .click();
    await expect(
      this.page.getByRole('dialog', { name: 'Delete Development Chat' }),
    ).toBeVisible();
  }

  async cancelDeletion() {
    await this.page.getByRole('button', { name: 'Cancel' }).click();
    await expect(
      this.page.getByRole('dialog', { name: 'Delete Development Chat' }),
    ).not.toBeVisible();
  }

  async confirmDeletion() {
    await this.page.getByRole('button', { name: 'Delete permanently' }).click();
    await expect(
      this.page.getByRole('dialog', { name: 'Delete Development Chat' }),
    ).not.toBeVisible();
  }

  async loadOlderMessages() {
    const loadOlderButton = this.page.getByRole('button', {
      name: 'Load older messages',
    });
    await expect(loadOlderButton).toBeVisible();
    const messages = this.page.locator('article');
    const previousCount = await messages.count();
    await loadOlderButton.click();
    await expect.poll(() => messages.count()).toBeGreaterThan(previousCount);
  }

  async visibleMessageContents() {
    return this.page.locator('article').evaluateAll((messages) =>
      messages.map((message) =>
        message.textContent.replace(/^(user|assistant): /, ''),
      ),
    );
  }

  async submitExploration(content, expectedResponse) {
    await this.page.getByRole('textbox', { name: 'Exploration message' }).fill(content);
    await this.page.getByRole('button', { name: 'Send exploration' }).click();
    await expect(this.page.getByText(expectedResponse, { exact: true })).toBeVisible({
      timeout: 60_000,
    });
  }

  async startStreamedExploration(content) {
    await this.page.evaluate(() => {
      window.__developObservedActivity = [];
      window.__developObservedResponses = [];
      window.__developObservedStrongText = [];
      window.__developObservedUnsafeImage = false;
      window.__developActivityObserver?.disconnect();
      window.__developActivityObserver = new MutationObserver(() => {
        const stream = document.querySelector(
          'article[aria-label="Streaming assistant response"]',
        );
        const activity = Array.from(
          stream?.querySelectorAll('ol li') ?? [],
          (item) => item.textContent,
        );
        for (const item of activity) {
          if (!window.__developObservedActivity.includes(item)) {
            window.__developObservedActivity.push(item);
          }
        }
        if (stream) {
          window.__developObservedResponses.push(stream.textContent ?? '');
          window.__developObservedStrongText.push(
            ...Array.from(stream.querySelectorAll('strong'), (item) => item.textContent),
          );
          window.__developObservedUnsafeImage ||= Boolean(stream.querySelector('img'));
        }
      });
      window.__developActivityObserver.observe(document.body, {
        childList: true,
        subtree: true,
      });
    });
    await this.page.getByRole('textbox', { name: 'Exploration message' }).fill(content);
    await this.page.getByRole('button', { name: 'Send exploration' }).click();
  }

  proposal() {
    return this.page.getByRole('article', { name: 'Proposal' });
  }

  async makeItHappen() {
    await this.page.getByRole('button', { name: 'Make it happen' }).click();
    await expect(this.proposal()).toBeVisible({ timeout: 60_000 });
  }

  async expectProposalActions() {
    await expect(this.proposal().getByRole('button', { name: 'Approve' })).toBeEnabled();
    await expect(this.proposal().getByRole('button', { name: 'Reject' })).toBeEnabled();
  }

  async approveProposal() {
    await this.proposal().getByRole('button', { name: 'Approve' }).click();
    await expect(this.proposal().getByRole('button', { name: 'Approve' })).toBeDisabled();
  }

  async rejectProposal() {
    await this.proposal().getByRole('button', { name: 'Reject' }).click();
    await expect(this.proposal().getByText('rejected', { exact: true })).toBeVisible();
  }

  async expectOrderedActivity(expectedActivity) {
    await expect.poll(() =>
      this.page.evaluate(() => window.__developObservedActivity ?? []),
    ).toEqual(expectedActivity);
  }

  async expectSafeMarkdownResponse(text) {
    await expect.poll(() =>
      this.page.evaluate(
        (expected) =>
          (window.__developObservedResponses ?? []).some((value) =>
            value.includes(expected),
          ),
        text,
      ),
    ).toBe(true);
    await expect.poll(() =>
      this.page.evaluate(
        (expected) => (window.__developObservedStrongText ?? []).includes(expected),
        text,
      ),
    ).toBe(true);
    expect(
      await this.page.evaluate(() => window.__developObservedUnsafeImage),
    ).toBe(false);
  }
}

module.exports = { DevelopPage };