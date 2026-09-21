## 1. First-time setup — skip this whole section if `acceptance-tests/` already exists

- [ ] 1.1 Confirm the acceptance stack: `stack: javascript` is already recorded in `openspec/config.yaml`, so no specs-zone edit is needed — verify it still reads `javascript` before scaffolding
- [ ] 1.2 Verify the application skeleton boots end to end with the repo's existing Docker Compose setup (`compose.yml` + `compose.override.yml`), so the suite has a backend and frontend to drive
- [ ] 1.3 Create `acceptance-tests/` at the repo root as an independent Node project (`acceptance-tests/package.json`) with devDependencies `@cucumber/cucumber`, `glob`, `cheerio`, `gherkin-lint`, plus Playwright for driving the React SPA; add `acceptance-tests/support/world.js` and `acceptance-tests/support/hooks.js` that boot the app before the suite and shut it down after
- [ ] 1.4 Copy the acceptance-test-authoring skill's javascript reference files verbatim into `acceptance-tests/` — `references/javascript/extract-gherkin.cjs` → `acceptance-tests/extract-gherkin.cjs`, `references/javascript/cucumber.cjs` → `acceptance-tests/cucumber.cjs`, `references/javascript/openspec-effective-paths.cjs` → `acceptance-tests/openspec-effective-paths.cjs`, `references/gherkin-lintrc.json` → `acceptance-tests/.gherkin-lintrc` — then confirm `npx cucumber-js --dry-run` discovers the extracted features from every `spec.md` under `openspec/` and loads nothing from `openspec/changes/archive/`
- [ ] 1.5 Make `npm --prefix acceptance-tests test` always generate an HTML report under `acceptance-tests/reports/`
- [ ] 1.6 Add `"lint:specs": "node extract-gherkin.cjs && gherkin-lint .extracted"` and the `test:specs` source-of-truth profile to `acceptance-tests/package.json`, and gitignore `acceptance-tests/.extracted/` and `acceptance-tests/reports/`
- [ ] 1.7 Write `acceptance-tests/README.md` covering how to run the suite, the source-of-truth regression run, the spec lint, and where the HTML report is written

## 2. Backend bulk-delete endpoint

- [ ] 2.1 Add a request model for the target user ids in `backend/app/models.py`, reusing `Message` as the response model
- [ ] 2.2 Register `POST /users/bulk-delete` in `backend/app/api/routes/users.py` before the `/{user_id}` routes, guarded by `Depends(get_current_active_superuser)` and taking `CurrentUser`
- [ ] 2.3 Validate the full target set before any mutation — reject empty list, duplicate ids, the current user's id, and unknown ids — each with its own `detail` message
- [ ] 2.4 Delete the owned `Item` rows with a single `in_` statement and the `User` rows in one transaction, committing only after the whole set validates
- [ ] 2.5 Add backend tests in `backend/app/tests/api/routes/test_users.py` for success with cascade, non-superuser rejection, empty list, duplicates, self-targeting, and unknown id leaving all data intact
- [ ] 2.6 Regenerate the frontend client with `scripts/generate-client.sh` and confirm the generated `UsersService` exposes the bulk operation

## 3. Admin selection and bulk action UI

- [ ] 3.1 Add opt-in row-selection props to `frontend/src/components/Common/DataTable.tsx` (default off) that expose the current page's selected rows and reset selection on demand
- [ ] 3.2 Add the checkbox column to `frontend/src/components/Admin/columns.tsx`, disabling selection for rows where `isCurrentUser` is true and scoping the header select-all to the visible page
- [ ] 3.3 Add `frontend/src/components/Admin/DeleteUsers.tsx` — the count-based confirmation dialog with the Items warning, `LoadingButton` pending state, auto-close on any response, success and error toasts carrying the backend `detail`, and `invalidateQueries` on settle
- [ ] 3.4 Render the always-visible `Delete User(s)` action next to `Add User` in `frontend/src/routes/_layout/admin.tsx`, disabled while the selection is empty, and clear the selection after a successful deletion
- [ ] 3.5 Add Playwright coverage in `frontend/tests/admin.spec.ts` for selection, current-user protection, page-scoped select-all, button enablement, cancellation, and the success and failure notifications

## 4. Step definitions — one task per pending step; each = fails for the right reason → implement → passes → commit

- [ ] 4.1 Selecting, deselecting, and counting eligible users in the admin table — red → green → commit
- [ ] 4.2 The current user's checkbox is disabled and excluded from the count — red → green → commit
- [ ] 4.3 Select-all covers the current page only — red → green → commit
- [ ] 4.4 `Delete User(s)` visibility and enablement relative to the selection — red → green → commit
- [ ] 4.5 The confirmation dialog states the count and the Items warning — red → green → commit
- [ ] 4.6 Cancelling the dialog sends no request and leaves the table unchanged — red → green → commit
- [ ] 4.7 Confirming shows the disabled confirm control with a spinner until the dialog auto-closes — red → green → commit
- [ ] 4.8 A superuser deletes the selected users and their Items — red → green → commit
- [ ] 4.9 A non-superuser bulk-delete request is rejected as unauthorized — red → green → commit
- [ ] 4.10 Empty and duplicate target lists are rejected with their reasons — red → green → commit
- [ ] 4.11 An unknown id and a self-targeting id each reject the whole request with nothing deleted — red → green → commit
- [ ] 4.12 Success and failure notifications, including the rejection reason, and the resulting table state — red → green → commit

## 5. Completion

- [ ] 5.1 Run `npm --prefix acceptance-tests run lint:specs` and fix every reported issue
- [ ] 5.2 Run the full effective suite: every scenario passes, zero pending/undefined steps, HTML report generated under `acceptance-tests/reports/`
- [ ] 5.3 Run the source-of-truth-only regression profile and confirm no archived or duplicate scenarios are loaded
