# admin-bulk-user-delete

Superusers manage the Users table from the admin page. This capability lets
a superuser select several users at once and delete them all in a single
atomic operation, instead of repeating the single-user delete flow.

## ADDED Requirements

### Requirement: Row selection with current-user protection
Each row in the admin Users table SHALL show a checkbox that toggles
selection of that user, and the checkbox for the currently authenticated
user's own row SHALL be disabled so it cannot be selected.

#### Scenario: Superuser selects another user's row

```gherkin
Given the superuser is viewing the admin Users table
When the superuser checks the checkbox on another user's row
Then that user's row becomes selected
```

#### Scenario: Current user's row cannot be selected

```gherkin
Given the superuser is viewing the admin Users table
When the superuser looks at their own row
Then the checkbox on that row is disabled and cannot be checked
```

### Requirement: Page-scoped select-all
The Users table SHALL provide a select-all control that selects or
deselects only the users on the currently visible page, and SHALL NOT
affect users on other pages.

#### Scenario: Select-all selects only the visible page

```gherkin
Given the Users table is showing one page of a larger user list
When the superuser activates select-all
Then every selectable row on the current page becomes selected
And users on other pages remain unselected
```

#### Scenario: Select-all skips the current user's row

```gherkin
Given the current user's row is present on the visible page
When the superuser activates select-all
Then every other selectable row on the page becomes selected
And the current user's row remains unselected
```

### Requirement: Delete User(s) action visibility and state
The admin Users page SHALL always display a `Delete User(s)` button next to
the `Add User` button, and the `Delete User(s)` button SHALL be disabled
whenever no user is selected.

#### Scenario: Button is disabled with no selection

```gherkin
Given the superuser is viewing the admin Users table
And no user rows are selected
Then the `Delete User(s)` button is visible and disabled
```

#### Scenario: Button becomes enabled once a user is selected

```gherkin
Given the superuser is viewing the admin Users table
When the superuser selects at least one user row
Then the `Delete User(s)` button becomes enabled
```

### Requirement: Bulk delete confirmation dialog
Activating the `Delete User(s)` button SHALL open a confirmation dialog
that states the number of selected users and the existing warning that
their Items are also permanently deleted. Upon confirmation, the dialog's
confirm control SHALL be disabled and show a spinner until the operation's
response is received, at which point the dialog SHALL close automatically.

#### Scenario: Dialog shows selected count and warning

```gherkin
Given the superuser has selected 3 users
When the superuser clicks the `Delete User(s)` button
Then a confirmation dialog opens
And the dialog states that 3 users will be deleted
And the dialog warns that their Items are also permanently deleted
```

#### Scenario: Dialog shows a spinner while the request is pending

```gherkin
Given the bulk delete confirmation dialog is open
When the superuser confirms the deletion
Then the confirm control is disabled and shows a spinner
And the dialog remains open until a response is received
```

#### Scenario: Dialog closes automatically once a response is received

```gherkin
Given the superuser confirmed the bulk deletion and the request is pending
When the backend responds to the bulk delete request
Then the confirmation dialog closes automatically
```

### Requirement: Bulk delete result notifications
The admin page SHALL display a success notification when the bulk delete
operation succeeds, and SHALL display a failure notification when the
operation is rejected.

#### Scenario: Success notification on successful bulk deletion

```gherkin
Given the superuser confirmed deletion of the selected users
When the backend reports the bulk deletion succeeded
Then a success notification is displayed
```

#### Scenario: Failure notification on rejected bulk deletion

```gherkin
Given the superuser confirmed deletion of the selected users
When the backend rejects the bulk delete request
Then a failure notification is displayed
And no users are removed from the table
```

### Requirement: Atomic bulk delete endpoint
The backend SHALL expose a dedicated endpoint, restricted to superusers,
that deletes a set of users identified by their IDs in a single atomic
transaction: either every targeted user (and their Items) is deleted, or
none are.

#### Scenario: All selected users are deleted together

```gherkin
Given a superuser submits a bulk delete request for 3 valid user IDs
When the backend processes the request
Then all 3 users are deleted
And the request succeeds
```

#### Scenario: Non-superuser cannot call the bulk delete endpoint

```gherkin
Given a non-superuser is authenticated
When they submit a bulk delete request
Then the request is rejected
And no users are deleted
```

### Requirement: Bulk delete rejects invalid or self-targeting requests
The bulk delete operation SHALL reject the entire request, deleting no
users, when any targeted ID does not correspond to an existing user or
when the targeted IDs include the requesting superuser's own ID.

#### Scenario: Request containing a nonexistent user ID is rejected

```gherkin
Given a bulk delete request includes one user ID that does not exist
When the backend processes the request
Then the request is rejected
And none of the targeted users are deleted
```

#### Scenario: Request targeting the current superuser is rejected

```gherkin
Given a bulk delete request includes the requesting superuser's own ID
When the backend processes the request
Then the request is rejected
And none of the targeted users are deleted
```

### Requirement: Cascading deletion of Items on bulk delete
When a bulk delete request succeeds, the backend SHALL delete all Items
owned by each deleted user as part of the same atomic transaction.

#### Scenario: Items owned by deleted users are removed

```gherkin
Given 2 selected users each own one or more Items
When the bulk delete request succeeds
Then all Items owned by those 2 users are also deleted
```
