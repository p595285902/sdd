const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { Given, Then, When } = require('@cucumber/cucumber');
const { expect } = require('@playwright/test');

async function openAdminWithUsers(world, count) {
  const token = await world.apiClient.authenticateSuperuser();
  world.users = await Promise.all(
    Array.from({ length: count }, () => world.apiClient.createUser()),
  );
  await world.adminUsersPage.open(token);
}

async function submitBulkDelete(world) {
  world.response = await world.apiClient.bulkDelete(world.requestToken, world.requestedIds);
}

Given('a superuser is viewing a page of the admin Users table', async function () {
  await openAdminWithUsers(this, 2);
});

When('the superuser selects two other user rows', async function () {
  await this.adminUsersPage.selectUsers(this.users);
});

Then('both users are selected for bulk deletion', async function () {
  await this.adminUsersPage.expectUsersSelected(this.users);
});

Given('a superuser is viewing their own row in the admin Users table', async function () {
  const token = await this.apiClient.authenticateSuperuser();
  this.currentUser = await this.apiClient.currentUser();
  await this.adminUsersPage.open(token);
});

Then("the selection checkbox for the current user's row is disabled", async function () {
  await expect(this.adminUsersPage.selectionFor(this.currentUser.email)).toBeDisabled();
});

Given('a superuser is viewing one page of a multi-page admin Users table', async function () {
  await openAdminWithUsers(this, 10);
  await this.adminUsersPage.setPageSize(5);
});

When('the superuser selects all users on the visible page', async function () {
  this.firstPageEmails = await this.adminUsersPage.visibleUserEmails();
  await this.adminUsersPage.selectAll().check();
});

Then('every eligible user on the visible page is selected', async function () {
  const currentEmail = this.applicationState.env.FIRST_SUPERUSER;
  const eligibleUsers = this.firstPageEmails
    .filter((email) => email !== currentEmail)
    .map((email) => ({ email }));
  await this.adminUsersPage.expectUsersSelected(eligibleUsers);
});

Then('users on other pages are not selected', async function () {
  await this.adminUsersPage.nextPage();
  await this.adminUsersPage.expectVisibleUsersNotSelected();
});

Then('the current user is not selected', async function () {
  const currentUserCheckbox = this.adminUsersPage.selectionFor(
    this.applicationState.env.FIRST_SUPERUSER,
  );
  if (await currentUserCheckbox.count()) await expect(currentUserCheckbox).not.toBeChecked();
});

Given('a superuser is viewing the admin Users table', async function () {
  await openAdminWithUsers(this, 0);
});

Given('no users are selected', async function () {});

Then(/^the Delete User\(s\) action is visible next to the Add User action$/, async function () {
  await this.adminUsersPage.expectDeleteActionsVisibleTogether();
});

Then(/^the Delete User\(s\) action is disabled$/, async function () {
  await expect(this.adminUsersPage.deleteAction()).toBeDisabled();
});

Given('a superuser has selected an eligible user', async function () {
  await openAdminWithUsers(this, 1);
  await this.adminUsersPage.selectUsers(this.users);
});

Then(/^the Delete User\(s\) action is enabled$/, async function () {
  await expect(this.adminUsersPage.deleteAction()).toBeEnabled();
});

Given('a superuser has selected three eligible users', async function () {
  await openAdminWithUsers(this, 3);
  await this.adminUsersPage.selectUsers(this.users);
});

When('the superuser starts bulk deletion', async function () {
  await this.adminUsersPage.startDeletion();
});

Then('a confirmation dialog states that three users will be deleted', async function () {
  await expect(this.adminUsersPage.dialog()).toContainText('3 users will be deleted');
});

Then('the dialog warns that their Items will also be permanently deleted', async function () {
  await expect(this.adminUsersPage.dialog()).toContainText('Items');
  await expect(this.adminUsersPage.dialog()).toContainText('permanently deleted');
});

Given('a superuser has confirmed bulk deletion', async function () {
  await openAdminWithUsers(this, 1);
  await this.adminUsersPage.holdBulkDeleteResponse();
  await this.adminUsersPage.selectUsers(this.users);
  await this.adminUsersPage.startDeletion();
  await this.adminUsersPage.confirmDeletion();
});

When('the deletion request is pending', async function () {
  await expect(this.adminUsersPage.confirmationAction()).toBeDisabled();
});

Then('the confirmation action is disabled', async function () {
  await expect(this.adminUsersPage.confirmationAction()).toBeDisabled();
});

Then('a loading spinner is visible', async function () {
  await expect(this.adminUsersPage.confirmationAction().locator('svg.animate-spin')).toBeVisible();
  this.adminUsersPage.releaseBulkDeleteResponse();
});

Given('a bulk deletion request is pending in the confirmation dialog', async function () {
  await openAdminWithUsers(this, 1);
  await this.adminUsersPage.holdBulkDeleteResponse();
  await this.adminUsersPage.selectUsers(this.users);
  await this.adminUsersPage.startDeletion();
  await this.adminUsersPage.confirmDeletion();
});

When('the server responds to the request', function () {
  this.adminUsersPage.releaseBulkDeleteResponse();
});

Then('the confirmation dialog closes automatically', async function () {
  await expect(this.adminUsersPage.dialog()).not.toBeVisible();
});

Given('a superuser confirms deletion of selected eligible users', async function () {
  await openAdminWithUsers(this, 2);
  await this.adminUsersPage.selectUsers(this.users);
  await this.adminUsersPage.startDeletion();
  await this.adminUsersPage.confirmDeletion();
});

When('the bulk deletion succeeds', async function () {
  await expect(this.adminUsersPage.dialog()).not.toBeVisible();
});

Then('a success notification is displayed', async function () {
  await this.adminUsersPage.expectSuccessNotification();
});

Then('the deleted users no longer appear in the Users table', async function () {
  await this.adminUsersPage.expectUserRowsAbsent(this.users);
});

Given('a superuser confirms deletion of selected users', async function () {
  await openAdminWithUsers(this, 1);
  await this.adminUsersPage.rejectBulkDeleteResponse();
  await this.adminUsersPage.selectUsers(this.users);
  await this.adminUsersPage.startDeletion();
  await this.adminUsersPage.confirmDeletion();
});

When('the bulk deletion is rejected', async function () {
  if (this.response) assert.ok([403, 404, 422].includes(this.response.status()));
  else await expect(this.adminUsersPage.dialog()).not.toBeVisible();
});

Then('a failure notification is displayed', async function () {
  await this.adminUsersPage.expectFailureNotification();
});

Given('an authenticated superuser submits eligible user IDs for bulk deletion', async function () {
  this.requestToken = await this.apiClient.authenticateSuperuser();
  this.users = [await this.apiClient.createUser()];
  this.requestedIds = this.users.map((user) => user.id);
});

When('the request is authorized', async function () {
  await submitBulkDelete(this);
});

Then('the system processes the bulk deletion', function () {
  assert.equal(this.response.status(), 200);
});

Given('an authenticated non-superuser submits user IDs for bulk deletion', async function () {
  await this.apiClient.authenticateSuperuser();
  const regularUser = await this.apiClient.createUser();
  this.users = [await this.apiClient.createUser()];
  this.requestToken = await this.apiClient.authenticate(regularUser.email, regularUser.password);
  this.requestedIds = this.users.map((user) => user.id);
});

Then('no users are deleted', async function () {
  for (const user of this.users) assert.equal(await this.apiClient.userExists(user.id), true);
});

Given('a superuser submits IDs for existing users other than the current user', async function () {
  this.requestToken = await this.apiClient.authenticateSuperuser();
  this.users = [await this.apiClient.createUser(), await this.apiClient.createUser()];
  this.requestedIds = this.users.map((user) => user.id);
});

When('the bulk deletion is processed', async function () {
  await submitBulkDelete(this);
});

Then('every requested user is deleted in one operation', async function () {
  assert.equal(this.response.status(), 200);
  for (const user of this.users) assert.equal(await this.apiClient.userExists(user.id), false);
});

Given('a superuser submits one existing user ID and one nonexistent user ID', async function () {
  this.requestToken = await this.apiClient.authenticateSuperuser();
  this.users = [await this.apiClient.createUser()];
  this.requestedIds = [this.users[0].id, randomUUID()];
});

Then('the existing user is not deleted', async function () {
  assert.equal(await this.apiClient.userExists(this.users[0].id), true);
});

Given('a superuser submits their own ID and another existing user ID', async function () {
  this.requestToken = await this.apiClient.authenticateSuperuser();
  const currentUser = await this.apiClient.currentUser();
  this.users = [await this.apiClient.createUser()];
  this.requestedIds = [currentUser.id, this.users[0].id];
});

Then('neither user is deleted', async function () {
  const currentUser = await this.apiClient.currentUser();
  assert.equal(currentUser.id, this.requestedIds[0]);
  assert.equal(await this.apiClient.userExists(this.users[0].id), true);
});

Given('selected users own Items', async function () {
  this.requestToken = await this.apiClient.authenticateSuperuser();
  this.users = [await this.apiClient.createUser(), await this.apiClient.createUser()];
  this.items = [];
  for (const user of this.users) this.items.push(await this.apiClient.createItem(user));
  this.requestedIds = this.users.map((user) => user.id);
});

When('a superuser successfully deletes those users in bulk', async function () {
  await submitBulkDelete(this);
  assert.equal(this.response.status(), 200);
});

Then('the selected users are deleted', async function () {
  for (const user of this.users) assert.equal(await this.apiClient.userExists(user.id), false);
});

Then('all Items owned by the selected users are deleted', async function () {
  const remainingItemIds = new Set((await this.apiClient.listItems()).map((item) => item.id));
  for (const item of this.items) assert.equal(remainingItemIds.has(item.id), false);
});