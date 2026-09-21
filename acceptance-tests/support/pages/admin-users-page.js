const assert = require('node:assert/strict');
const { expect } = require('@playwright/test');

class AdminUsersPage {
  constructor(world) {
    this.world = world;
  }

  get page() {
    return this.world.page;
  }

  async open(token) {
    await this.page.addInitScript((accessToken) => {
      localStorage.setItem('access_token', accessToken);
    }, token);
    await this.page.goto('/admin');
    await expect(this.page.getByRole('heading', { name: 'Users' })).toBeVisible();
  }

  selectionFor(email) {
    return this.page.getByLabel(`Select ${email}`);
  }

  selectAll() {
    return this.page.getByLabel('Select all users on current page');
  }

  deleteAction() {
    return this.page.getByRole('button', { name: 'Delete User(s)' });
  }

  confirmationAction() {
    return this.page.getByRole('button', { name: 'Delete users', exact: true });
  }

  dialog() {
    return this.page.getByRole('dialog');
  }

  async selectUsers(users) {
    for (const user of users) await this.selectionFor(user.email).check();
  }

  async setPageSize(size) {
    await this.page.getByRole('combobox').click();
    await this.page
      .getByRole('option', { name: String(size), exact: true })
      .click();
  }

  async nextPage() {
    await this.page.getByRole('button', { name: 'Go to next page' }).click();
  }

  async visibleUserEmails() {
    return this.page
      .getByRole('checkbox', { name: /^Select / })
      .evaluateAll((checkboxes) =>
        checkboxes.map((checkbox) => checkbox.getAttribute('aria-label').slice(7)),
      );
  }

  async startDeletion() {
    await this.deleteAction().click();
  }

  async confirmDeletion() {
    await this.confirmationAction().click();
  }

  async holdBulkDeleteResponse(status = 200, body = { message: 'ok' }) {
    this.releaseResponse = undefined;
    await this.page.route('**/api/v1/users/bulk-delete', async (route) => {
      await new Promise((resolve) => {
        this.releaseResponse = resolve;
      });
      await route.fulfill({ status, json: body });
    });
  }

  releaseBulkDeleteResponse() {
    this.releaseResponse?.();
  }

  async rejectBulkDeleteResponse() {
    await this.page.route('**/api/v1/users/bulk-delete', (route) =>
      route.fulfill({ status: 404, json: { detail: 'User not found' } }),
    );
  }

  async expectUsersSelected(users) {
    for (const user of users) await expect(this.selectionFor(user.email)).toBeChecked();
  }

  async expectUsersNotSelected(users) {
    for (const user of users) await expect(this.selectionFor(user.email)).not.toBeChecked();
  }

  async expectVisibleUsersNotSelected() {
    const checkboxes = this.page.getByRole('checkbox', { name: /^Select / });
    for (const checkbox of await checkboxes.all()) await expect(checkbox).not.toBeChecked();
  }

  async expectDeleteActionsVisibleTogether() {
    const deleteAction = this.deleteAction();
    const addAction = this.page.getByRole('button', { name: 'Add User' });
    await expect(deleteAction).toBeVisible();
    await expect(addAction).toBeVisible();
    const addElement = await addAction.elementHandle();
    assert.equal(
      await deleteAction.evaluate(
        (button, sibling) => button.parentElement === sibling.parentElement,
        addElement,
      ),
      true,
    );
  }

  async expectSuccessNotification() {
    await expect(this.page.getByText('Users deleted successfully')).toBeVisible();
  }

  async expectFailureNotification() {
    await expect(this.page.getByText('Something went wrong!')).toBeVisible();
  }

  async expectUserRowsAbsent(users) {
    for (const user of users) {
      await expect(this.page.getByRole('row').filter({ hasText: user.email })).not.toBeVisible();
    }
  }
}

module.exports = { AdminUsersPage };