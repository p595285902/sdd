# Admin bulk user delete

Superusers can select visible users and delete them through one atomic operation while the signed-in superuser remains protected.

## ADDED Requirements

### Requirement: Eligible users can be selected for bulk deletion
The admin Users table SHALL provide a selection checkbox for every user row, MUST disable selection for the current user's row, and SHALL limit select-all to eligible users on the currently visible page.

#### Scenario: Superuser selects users individually

```gherkin
Given a superuser is viewing a page of the admin Users table
When the superuser selects two other user rows
Then both users are selected for bulk deletion
```

#### Scenario: Current user cannot be selected

```gherkin
Given a superuser is viewing their own row in the admin Users table
Then the selection checkbox for the current user's row is disabled
```

#### Scenario: Select all is limited to the visible page

```gherkin
Given a superuser is viewing one page of a multi-page admin Users table
When the superuser selects all users on the visible page
Then every eligible user on the visible page is selected
And users on other pages are not selected
And the current user is not selected
```

### Requirement: Bulk delete action reflects selection state
The admin Users page SHALL display a `Delete User(s)` action next to `Add User` and MUST disable it when no users are selected.

#### Scenario: Bulk delete action is disabled without a selection

```gherkin
Given a superuser is viewing the admin Users table
And no users are selected
Then the Delete User(s) action is visible next to the Add User action
And the Delete User(s) action is disabled
```

#### Scenario: Bulk delete action is enabled with a selection

```gherkin
Given a superuser has selected an eligible user
Then the Delete User(s) action is enabled
```

### Requirement: Bulk deletion requires confirmation
The system MUST require confirmation before bulk deletion, SHALL state the number of selected users and warn that their Items will also be permanently deleted, and SHALL prevent duplicate submission while the request is pending.

#### Scenario: Confirmation describes the destructive operation

```gherkin
Given a superuser has selected three eligible users
When the superuser starts bulk deletion
Then a confirmation dialog states that three users will be deleted
And the dialog warns that their Items will also be permanently deleted
```

#### Scenario: Pending deletion cannot be submitted twice

```gherkin
Given a superuser has confirmed bulk deletion
When the deletion request is pending
Then the confirmation action is disabled
And a loading spinner is visible
```

#### Scenario: Confirmation dialog closes after a response

```gherkin
Given a bulk deletion request is pending in the confirmation dialog
When the server responds to the request
Then the confirmation dialog closes automatically
```

### Requirement: Bulk deletion reports its outcome
The admin Users page SHALL display a success notification after a successful bulk deletion and a failure notification when the operation is rejected.

#### Scenario: Successful deletion is reported

```gherkin
Given a superuser confirms deletion of selected eligible users
When the bulk deletion succeeds
Then a success notification is displayed
And the deleted users no longer appear in the Users table
```

#### Scenario: Rejected deletion is reported

```gherkin
Given a superuser confirms deletion of selected users
When the bulk deletion is rejected
Then a failure notification is displayed
```

### Requirement: Bulk deletion is restricted to superusers
The bulk-delete endpoint MUST permit only authenticated superusers to delete users.

#### Scenario: Superuser can request bulk deletion

```gherkin
Given an authenticated superuser submits eligible user IDs for bulk deletion
When the request is authorized
Then the system processes the bulk deletion
```

#### Scenario: Regular user cannot request bulk deletion

```gherkin
Given an authenticated non-superuser submits user IDs for bulk deletion
When the request is authorized
Then the bulk deletion is rejected
And no users are deleted
```

### Requirement: Bulk deletion is atomic
The bulk-delete endpoint MUST validate every requested user ID before deleting any user and MUST reject the entire operation when a target does not exist or identifies the current user.

#### Scenario: All valid targets are deleted

```gherkin
Given a superuser submits IDs for existing users other than the current user
When the bulk deletion is processed
Then every requested user is deleted in one operation
```

#### Scenario: Missing target rejects the entire operation

```gherkin
Given a superuser submits one existing user ID and one nonexistent user ID
When the bulk deletion is processed
Then the bulk deletion is rejected
And the existing user is not deleted
```

#### Scenario: Current user target rejects the entire operation

```gherkin
Given a superuser submits their own ID and another existing user ID
When the bulk deletion is processed
Then the bulk deletion is rejected
And neither user is deleted
```

#### Scenario: Duplicate targets is rejected

```gherkin
Given a superuser submits the same existing eligible user ID more than once
When the bulk deletion is processed
Then the bulk deletion is rejected
And neither user is deleted
```

#### Scenario: Empty target set is rejected

```gherkin
Given a superuser submits an empty user ID set for bulk deletion
When the bulk deletion is processed
Then the bulk deletion is rejected
And no users are deleted
```

### Requirement: Deleting users removes their owned Items
The system MUST permanently delete Items owned by every user deleted through the bulk-delete endpoint.

#### Scenario: Owned Items are deleted with their users

```gherkin
Given selected users own Items
When a superuser successfully deletes those users in bulk
Then the selected users are deleted
And all Items owned by the selected users are deleted
```