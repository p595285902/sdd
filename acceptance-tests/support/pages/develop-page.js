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

  repositoryButton(status) {
    return this.page.getByRole('button', { name: status });
  }

  async expectRepositoryStatus(status, color, explanation) {
    const button = this.repositoryButton(status);
    await expect(button.locator('svg')).toHaveClass(new RegExp(`text-${color}-600`));
    await expect(async () => {
      await this.page.mouse.move(0, 0);
      await button.locator('..').hover();
      await expect(this.page.getByRole('tooltip')).toContainText(explanation, { timeout: 1_500 });
    }).toPass({ timeout: 10_000 });
  }

  async expectRenameByTitle(title) {
    const group = this.page.getByRole('heading', { name: title }).locator('..');
    await expect(group.getByRole('button', { name: 'Rename Development Chat' })).toBeVisible();
  }

  async expectSelectedHeader(title) {
    await expect(this.page.getByRole('heading', { name: title })).toBeVisible();
  }

  async expectPresenceBesideDelete(label) {
    const mode = this.page.getByRole('combobox', { name: 'Presence Mode' });
    const deleteButton = this.page.getByRole('button', { name: 'Delete Development Chat' });
    await expect(mode).toHaveText(label);
    const modeBox = await mode.boundingBox();
    const deleteBox = await deleteButton.boundingBox();
    expect(modeBox).not.toBeNull();
    expect(deleteBox).not.toBeNull();
    expect(modeBox.x + modeBox.width).toBeLessThanOrEqual(deleteBox.x + 2);
  }

  async choosePresenceMode(label) {
    await this.page.getByRole('combobox', { name: 'Presence Mode' }).click();
    await this.page.getByRole('option', { name: label }).click();
  }

  async expectPresenceMode(label) {
    await expect(this.page.getByRole('combobox', { name: 'Presence Mode' })).toHaveText(label);
  }

  async useSmallScreen() {
    await this.page.setViewportSize({ width: 390, height: 844 });
  }

  async expectWrappedHeader(title) {
    const heading = this.page.getByRole('heading', { name: title });
    const titleBox = await heading.boundingBox();
    const modeBox = await this.page.getByRole('combobox', { name: 'Presence Mode' }).boundingBox();
    expect(titleBox).not.toBeNull();
    expect(modeBox).not.toBeNull();
    expect(modeBox.y).toBeGreaterThanOrEqual(titleBox.y + titleBox.height - 2);
    for (const control of [
      this.page.getByRole('button', { name: 'Rename Development Chat' }),
      this.repositoryButton('Set up demo repository'),
      this.page.getByRole('combobox', { name: 'Presence Mode' }),
      this.page.getByRole('button', { name: 'Delete Development Chat' }),
    ]) {
      await expect(control).toBeInViewport();
    }
  }

  async openMobileContext() {
    await this.page.getByRole('button', { name: 'Open development context' }).click();
    await expect(this.page.getByRole('complementary', { name: 'Development context' }).last()).toBeVisible();
  }

  async expectEmptyMobileContext() {
    await expect(
      this.page.getByRole('complementary', { name: 'Development context' }).last()
        .getByText('No additional context'),
    ).toBeVisible();
  }

  async startHeldRepositorySetup() {
    await this.page.route('**/api/v1/develop/chats/*/workspace/setup', async (route) => {
      await new Promise((resolve) => { this.releaseRepositorySetup = resolve; });
      await route.continue();
    });
    await this.repositoryButton('Set up demo repository').click();
    await expect(this.repositoryButton('Repository setup in progress')).toBeVisible();
  }

  async finishHeldRepositorySetup() {
    this.releaseRepositorySetup();
    await expect(this.repositoryButton('Demo repository ready')).toBeVisible();
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

  async expectRunningActivityDuration() {
    const streaming = this.page.getByRole('article', { name: 'Streaming assistant response' });
    await expect(streaming.locator('summary')).toContainText(/Agent activity · \d+:\d{2}/);
  }

  async expectPersistedActivityDuration(content, seconds) {
    const message = this.page.locator('article', { hasText: content });
    const duration = `${Math.floor(seconds / 60)}:${(Math.floor(seconds) % 60).toString().padStart(2, '0')}`;
    await expect(message.locator('summary')).toHaveText(`Agent activity · ${duration}`);
  }
}

module.exports = { DevelopPage };