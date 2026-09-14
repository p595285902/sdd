# admin-bulk-user-delete

## ADDED Requirements

### Requirement: Admin users can select deletable users on the current page

The admin Users table MUST provide a checkbox for each displayed user and MUST prevent the current superuser from being selected as a delete target.

#### Scenario: Select an eligible user

```gherkin
Given a superuser is viewing the admin Users table
And an eligible user is displayed on the current page
When the superuser selects that user's checkbox
Then the user is marked as selected
And the Delete User(s) action becomes enabled
```

#### Scenario: Current user cannot be selected

```gherkin
Given a superuser is viewing the admin Users table
And the current superuser is displayed on the current page
Then the current user's checkbox is disabled
And the current user is not included in the selected-user count
```

#### Scenario: Select all is limited to the current page

```gherkin
Given a superuser is viewing a paginated admin Users table
And users are displayed on the current page
When the superuser selects the table select-all checkbox
Then every eligible user on the current page is selected
And users on other pages are not selected
```

### Requirement: Admin users can initiate bulk deletion

The admin Users page MUST show a `Delete User(s)` action next to `Add User`, and the action MUST be disabled when no eligible users are selected. When confirmed, the confirmation dialog MUST remain open with the confirm button disabled and a spinning icon displayed until the dialog closes automatically upon receiving any response.

#### Scenario: Bulk action is disabled without a selection

```gherkin
Given a superuser is viewing the admin Users page
And no eligible users are selected
Then the Delete User(s) action is visible next to Add User
And the Delete User(s) action is disabled
```

#### Scenario: Bulk action opens a count-based confirmation

```gherkin
Given a superuser has selected three eligible users on the current page
When the superuser clicks Delete User(s)
Then a confirmation dialog is displayed
And the dialog states that three users will be deleted
And the dialog warns that Items owned by those users will also be permanently deleted
```

#### Scenario: Confirming bulk deletion shows loading state and closes on response

```gherkin
Given the bulk-delete confirmation dialog is open
When the superuser confirms bulk deletion
Then the confirmation dialog remains open
And the confirm button is disabled
And a spinning icon is displayed within the confirm button
And the confirmation dialog closes automatically when a response is received
```

### Requirement: Bulk deletion is atomic and authorized

The system MUST provide a superuser-only bulk-delete operation that accepts selected user IDs, rejects an empty or duplicate target list, deletes all valid targets and their owned Items in one transaction, and rejects the entire operation without deletion when any target is invalid or is the current user. When a bulk-delete request is rejected, the failure notification MUST include the specific reason the request failed so the user understands why the operation was blocked.

#### Scenario: Bulk deletion rejects an empty target list

```gherkin
Given an authenticated superuser
When the superuser submits a bulk-delete request with no user IDs
Then the operation is rejected
And no users or Items are deleted
And a failure notification is displayed
And the failure notification explains that no users were selected for deletion
```

#### Scenario: Bulk deletion rejects duplicate target IDs

```gherkin
Given an authenticated superuser
When the superuser submits a bulk-delete request containing the same user ID more than once
Then the operation is rejected
And no users or Items are deleted
And a failure notification is displayed
And the failure notification explains that duplicate users were included in the request
```

#### Scenario: Superuser deletes selected users successfully

```gherkin
Given an authenticated superuser has selected two other users
When the superuser confirms bulk deletion
Then the system deletes both users atomically
And the system deletes all Items owned by those users
And the admin Users table no longer displays those users
And a success notification is displayed
```

#### Scenario: Bulk deletion rejects the current user

```gherkin
Given an authenticated superuser submits a bulk-delete request containing their own user ID
When the bulk-delete operation is processed
Then the operation is rejected
And no users or Items from the request are deleted
And a failure notification is displayed
And the failure notification explains that the current user cannot be deleted
```

#### Scenario: Bulk deletion rejects an invalid target atomically

```gherkin
Given an authenticated superuser submits a bulk-delete request containing one nonexistent user ID and one existing user ID
When the bulk-delete operation is processed
Then the operation is rejected
And the existing user is not deleted
And the existing user's Items are not deleted
And a failure notification is displayed
And the failure notification explains that user ID is not found
```

#### Scenario: Non-superuser cannot bulk delete

```gherkin
Given an authenticated non-superuser
When the user submits a bulk-delete request
Then the operation is rejected as unauthorized
And no users or Items are deleted
```

#### Scenario: Cancelling confirmation does not delete users

```gherkin
Given a superuser has selected one or more eligible users
And the bulk-delete confirmation dialog is open
When the superuser cancels the dialog
Then the selected users remain in the table
And no users or Items are deleted
```
