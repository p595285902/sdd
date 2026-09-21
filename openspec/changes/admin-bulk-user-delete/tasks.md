## 1. First-time acceptance setup

- [ ] 1.1 Confirm `stack: javascript` remains configured in `openspec/config.yaml` and treat the generated-only `acceptance-tests/.extracted/` directory as not yet scaffolded
- [ ] 1.2 Create `acceptance-tests/package.json` as an independent Node project with `@cucumber/cucumber`, `glob`, `cheerio`, and `gherkin-lint`, plus `test`, `test:specs`, and `lint:specs` scripts
- [ ] 1.3 Copy the skill references to `acceptance-tests/extract-gherkin.cjs`, `acceptance-tests/cucumber.cjs`, `acceptance-tests/openspec-effective-paths.cjs`, and `acceptance-tests/.gherkin-lintrc` without modifying them
- [ ] 1.4 Add `acceptance-tests/features/support/hooks.js` and `acceptance-tests/features/support/world.js` so one test command starts the application, provides isolated test state, and always shuts the application down
- [ ] 1.5 Configure the cucumber-js default and source-of-truth profiles to generate HTML reports under `acceptance-tests/reports/`
- [ ] 1.6 Gitignore `acceptance-tests/.extracted/` and `acceptance-tests/reports/`, then verify extraction excludes `openspec/changes/archive/` and loads each effective scenario once
- [ ] 1.7 Write `acceptance-tests/README.md` with the JavaScript install, effective-suite, source-of-truth regression, spec-lint, dry-run, and HTML-report commands

## 2. Backend contract and atomic deletion

- [ ] 2.1 Add failing backend route tests for an empty request, a non-superuser, all-valid IDs, a nonexistent ID mixed with a valid ID, the current user's ID mixed with another ID, duplicate IDs, and deletion of owned Items
- [ ] 2.2 Add the non-empty bulk user-ID request model in `backend/app/models.py` and verify its OpenAPI schema
- [ ] 2.3 Add `POST /users/bulk-delete` before dynamic user-ID routes in `backend/app/api/routes/users.py`, protected by `get_current_active_superuser`
- [ ] 2.4 Fetch and validate the normalized target set before mutation, rejecting missing users or the current user without pending deletes
- [ ] 2.5 Delete target-owned Items and target users in the same session transaction with one commit, then make all focused backend tests pass

## 3. API acceptance steps

- [ ] 3.1 Implement authentication-context steps for authenticated superusers and non-superusers — red → green → commit
- [ ] 3.2 Implement request steps for eligible, missing, current-user, duplicate, and empty user-ID sets — red → green → commit
- [ ] 3.3 Implement authorization and bulk-processing action steps through the real HTTP endpoint — red → green → commit
- [ ] 3.4 Implement rejection and unchanged-user assertions proving invalid requests delete no users — red → green → commit
- [ ] 3.5 Implement successful user-deletion assertions for every requested unique ID — red → green → commit
- [ ] 3.6 Implement owned-Item fixtures and cascade assertions proving all Items for deleted users are removed — red → green → commit

## 4. Generated frontend client

- [ ] 4.1 Regenerate the backend OpenAPI document and run the existing `frontend` client-generation command
- [ ] 4.2 Verify the generated request type and `UsersService` bulk-delete method match the non-empty UUID-list contract, with no hand-written client edits

## 5. Admin selection behavior

- [ ] 5.1 Add failing frontend tests for individual selection, disabled current-user selection, current-page select-all, page isolation, and indeterminate header state
- [ ] 5.2 Extend `frontend/src/components/Common/DataTable.tsx` with optional controlled row selection, stable row IDs, and row eligibility while preserving existing consumers
- [ ] 5.3 Add accessible row and header checkboxes to the admin columns using TanStack current-page selection APIs
- [ ] 5.4 Own UUID-keyed selection state in the admin page, pass current-user eligibility to the table, and keep selections outside the visible page untouched by current-page select-all
- [ ] 5.5 Implement the table-viewing, individual-selection, current-user-disabled, and current-page select-all acceptance steps — red → green → commit

## 6. Bulk confirmation and notifications

- [ ] 6.1 Add failing frontend tests for the always-visible action, zero-selection disabled state, selected-state enablement, count and Item warning text, pending spinner, duplicate-submit prevention, automatic close, notifications, refresh, and selection cleanup
- [ ] 6.2 Add a bulk-delete component next to `Add User` that accepts selected UUIDs and opens a controlled confirmation dialog
- [ ] 6.3 Call the generated bulk-delete service through a React Query mutation, use `LoadingButton` for pending state, and close the dialog after either response
- [ ] 6.4 On success, show the success toast, clear selection, and invalidate the users query; on rejection, show the existing error toast without reporting success
- [ ] 6.5 Implement action visibility and enabled-state acceptance steps — red → green → commit
- [ ] 6.6 Implement confirmation count and permanent-Item-warning acceptance steps — red → green → commit
- [ ] 6.7 Implement pending disabled-button and loading-spinner acceptance steps — red → green → commit
- [ ] 6.8 Implement response-driven dialog-close acceptance steps for success and rejection — red → green → commit
- [ ] 6.9 Implement success notification and removed-row acceptance steps — red → green → commit
- [ ] 6.10 Implement rejection notification acceptance steps — red → green → commit

## 7. Completion

- [ ] 7.1 Run backend formatting, linting, type checks, and the full backend test suite
- [ ] 7.2 Run frontend formatting, linting, type checks, and the full Playwright suite
- [ ] 7.3 Run `openspec validate admin-bulk-user-delete --strict` and the extracted-spec lint command
- [ ] 7.4 Run the full effective acceptance suite with every scenario passing, zero pending or undefined steps, and an HTML report generated
- [ ] 7.5 Run the source-of-truth-only acceptance regression and verify the active delta is excluded from that profile