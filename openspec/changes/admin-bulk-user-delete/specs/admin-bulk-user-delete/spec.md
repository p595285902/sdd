# admin-bulk-user-delete

Superusers manage accounts from the admin Users page. This capability lets them
select several users at once from the currently visible table page and delete
them in a single atomic operation, while keeping the existing protection that a
superuser can never delete their own account. See proposal.md for motivation.

## ADDED Requirements

### Requirement: Admin users are selectable on the current table page

The admin Users table MUST render a selection checkbox on every displayed user row, MUST disable the checkbox on the current user's row so the current user can never become a delete target, and MUST scope select-all to the users visible on the current table page.

#### Scenario: Selecting an eligible user

```gherkin
Given a superuser is viewing the admin Users table
And an eligible user is displayed on the current page
When the superuser selects that user's checkbox
Then that user is marked as selected
And the selected-user count is one
```

#### Scenario: The current user's row cannot be selected

```gherkin
Given a superuser is viewing the admin Users table
And the current superuser is displayed on the current page
When the superuser inspects the current user's row
Then the current user's selection checkbox is disabled
And the current user is excluded from the selected-user count
```

#### Scenario: Select all covers only the current page

```gherkin
Given a superuser is viewing a paginated admin Users table
And eligible users are displayed on the current page
When the superuser selects the select-all checkbox
Then every eligible user on the current page is selected
And no user on another page is selected
```

#### Scenario: Deselecting a user removes it from the selection

```gherkin
Given a superuser has selected two eligible users on the current page
When the superuser clears one of those checkboxes
Then the selected-user count is one
And the remaining user stays selected
```

### Requirement: The bulk delete action is always visible and selection-gated

The admin Users page MUST display a `Delete User(s)` action next to `Add User` at all times, and the action MUST be disabled whenever no eligible user is selected and enabled as soon as at least one eligible user is selected.

#### Scenario: The action is disabled without a selection

```gherkin
Given a superuser is viewing the admin Users page
And no eligible user is selected
When the superuser looks at the page actions
Then the Delete User(s) action is displayed next to Add User
And the Delete User(s) action is disabled
```

#### Scenario: The action becomes enabled with a selection

```gherkin
Given a superuser is viewing the admin Users page
When the superuser selects an eligible user
Then the Delete User(s) action is enabled
```

### Requirement: Bulk deletion is confirmed before any data is removed

Activating `Delete User(s)` MUST open a confirmation dialog that states how many users will be deleted and warns that the Items owned by those users are also permanently deleted. Cancelling the dialog MUST NOT send any delete request. After the superuser confirms, the dialog MUST stay open with its confirm control disabled and a spinner displayed, and MUST close automatically once a response is received.

#### Scenario: Confirmation states the selected count and the Items warning

```gherkin
Given a superuser has selected three eligible users on the current page
When the superuser activates Delete User(s)
Then a confirmation dialog is displayed
And the dialog states that three users will be deleted
And the dialog warns that the Items owned by those users are permanently deleted
```

#### Scenario: Cancelling the confirmation deletes nothing

```gherkin
Given a superuser has selected eligible users on the current page
And the bulk delete confirmation dialog is displayed
When the superuser cancels the dialog
Then no bulk delete request is sent
And the selected users are still displayed in the admin Users table
```

#### Scenario: Confirming shows a pending state until a response arrives

```gherkin
Given the bulk delete confirmation dialog is displayed for two selected users
When the superuser confirms the deletion
Then the confirmation dialog stays open
And the confirm control is disabled
And a spinner is displayed in the confirm control
And the confirmation dialog closes automatically when a response is received
```

### Requirement: Bulk deletion is superuser-only and atomic

The system MUST expose a bulk delete operation that accepts a list of user identifiers, is restricted to superusers, and validates the whole target list before mutating any data. The operation MUST reject an empty list, a list containing duplicate identifiers, a list containing an unknown identifier, and a list containing the requesting superuser's own identifier. A rejected operation MUST delete no user and no Item. An accepted operation MUST delete every targeted user together with the Items they own in a single transaction.

#### Scenario: A superuser deletes the selected users

```gherkin
Given an authenticated superuser
And two other users exist, each owning Items
When the superuser submits a bulk delete request for both users
Then both users are deleted
And the Items owned by both users are deleted
And the admin Users table no longer displays those users
```

#### Scenario: A non-superuser cannot bulk delete

```gherkin
Given an authenticated user who is not a superuser
When the user submits a bulk delete request
Then the request is rejected as unauthorized
And no user is deleted
And no Item is deleted
```

#### Scenario: An empty target list is rejected

```gherkin
Given an authenticated superuser
When the superuser submits a bulk delete request with no user identifiers
Then the request is rejected
And the rejection reason states that no user was selected for deletion
And no user is deleted
```

#### Scenario: A duplicated target identifier is rejected

```gherkin
Given an authenticated superuser
When the superuser submits a bulk delete request containing the same user identifier twice
Then the request is rejected
And the rejection reason states that the request contains duplicate users
And no user is deleted
```

#### Scenario: An unknown target identifier rejects the whole request

```gherkin
Given an authenticated superuser
And an existing user who owns Items
When the superuser submits a bulk delete request for that user and an unknown user identifier
Then the request is rejected
And the rejection reason states that a user was not found
And the existing user is not deleted
And the Items owned by the existing user are not deleted
```

#### Scenario: Targeting the current user rejects the whole request

```gherkin
Given an authenticated superuser
And an existing user who owns Items
When the superuser submits a bulk delete request for that user and their own identifier
Then the request is rejected
And the rejection reason states that a superuser cannot delete themselves
And the existing user is not deleted
And the Items owned by the existing user are not deleted
```

### Requirement: The outcome of a bulk deletion is reported to the superuser

The admin Users page MUST display a success notification when a bulk deletion succeeds and MUST refresh the users table so the deleted users disappear. When a bulk deletion is rejected, the page MUST display a failure notification carrying the rejection reason returned by the system, and the table MUST keep showing the still-existing users.

#### Scenario: Success is reported

```gherkin
Given a superuser has confirmed the bulk deletion of two selected users
When the deletion succeeds
Then a success notification is displayed
And the admin Users table no longer displays the deleted users
And no user remains selected
```

#### Scenario: Failure is reported with its reason

```gherkin
Given a superuser has confirmed the bulk deletion of two selected users
When the deletion is rejected with a reason
Then a failure notification is displayed
And the failure notification contains the rejection reason
And the admin Users table still displays both users
```
