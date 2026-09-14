## 1. Specification and acceptance setup

- [ ] 1.1 Confirm the acceptance stack by reading `stack:` from `openspec/config.yaml`; if absent, ask the user and add the chosen value in a separate specs-only change before scaffolding acceptance infrastructure
- [ ] 1.2 Extract the new Gherkin spec and lint the extracted output with the repository's configured acceptance-test tooling

## 2. Backend bulk-delete contract

- [ ] 2.1 Add request and response models for a list of user UUIDs and define the dedicated bulk-delete route
- [ ] 2.2 Enforce superuser authorization and reject an empty or duplicate target list according to existing API conventions
- [ ] 2.3 Validate every target, reject nonexistent IDs and the current user's ID before mutation, and preserve all-or-nothing transaction behavior
- [ ] 2.4 Delete owned Items and Users within the transaction and add backend tests for success, unauthorized access, self-targeting, invalid targets, and rollback
- [ ] 2.5 Regenerate the frontend API client from the updated OpenAPI contract and verify generated types expose the bulk operation

## 3. Admin selection and bulk action UI

- [ ] 3.1 Extend the existing DataTable usage with row-selection state scoped to the current page
- [ ] 3.2 Add row checkboxes, a current-page select-all checkbox, and a disabled checkbox for the current user's row
- [ ] 3.3 Add the always-visible `Delete User(s)` button next to `Add User`, disabled when the selection is empty
- [ ] 3.4 Add the count-based bulk confirmation dialog, cancel behavior, success notification, query invalidation, and error handling
- [ ] 3.5 Add frontend tests for selection, current-user protection, current-page select-all, button state, confirmation, cancellation, and successful deletion

## 4. Acceptance coverage and completion

- [ ] 4.1 Add page-object and step-definition coverage for the admin bulk-delete scenarios in the configured acceptance stack
- [ ] 4.2 Run the effective acceptance suite and confirm all scenarios pass with an HTML report generated
- [ ] 4.3 Run the source-of-truth-only regression suite and confirm no archived or duplicate scenarios are loaded
