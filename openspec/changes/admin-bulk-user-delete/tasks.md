## 1. First-time setup — skip this whole section if `acceptance-tests/` already exists

- [ ] 1.1 Confirm the acceptance stack: `stack: javascript` is already set in `openspec/config.yaml` — no action needed
- [ ] 1.2 Confirm the existing backend (`backend/`) and frontend (`frontend/`) apps boot locally (e.g. via `compose.yml`) so the acceptance suite has something to drive
- [ ] 1.3 Create `acceptance-tests/` at the repo root as an independent Node project with its own `package.json` whose hooks boot the app before the suite and shut it down after
- [ ] 1.4 Copy the acceptance-test-authoring skill's javascript reference files verbatim into `acceptance-tests/`: `javascript/extract-gherkin.cjs` → `extract-gherkin.cjs`, `javascript/cucumber.cjs` → `cucumber.cjs`, `javascript/openspec-effective-paths.cjs` → `openspec-effective-paths.cjs`, and the shared `references/gherkin-lintrc.json` → `.gherkin-lintrc`
- [ ] 1.5 Add `@cucumber/cucumber`, `glob`, `cheerio`, `gherkin-lint` as devDependencies and add `test` (`cucumber-js`), `test:specs` (`cucumber-js -p specs`) and `lint:specs` (`node extract-gherkin.cjs && gherkin-lint .extracted`) scripts to `acceptance-tests/package.json`
- [ ] 1.6 Make `npm test` always generate an HTML report under `acceptance-tests/reports/`
- [ ] 1.7 Gitignore `acceptance-tests/.extracted/` and `acceptance-tests/reports/`
- [ ] 1.8 Write `acceptance-tests/README.md` with instructions for running the suite and where the HTML report is written

## 2. Backend bulk-delete contract

- [ ] 2.1 Add `UsersBulkDelete` request model (list of user UUIDs) to `backend/app/models.py`
- [ ] 2.2 Add `POST /users/bulk-delete` route in `backend/app/api/routes/users.py`, restricted via `get_current_active_superuser`
- [ ] 2.3 Load all targeted users in one query; if any ID is missing or the current user's ID is present, raise the appropriate `HTTPException` (404 / 403) and perform no deletion
- [ ] 2.4 On successful validation, delete each target's `Item` rows and then the `User` rows, and commit once as a single atomic transaction, returning a `Message` response
- [ ] 2.5 Add backend tests: successful bulk delete, non-superuser rejection, request containing a nonexistent ID, request containing the current user's ID, and cascading Item deletion — verify no partial deletion occurs on rejection
- [ ] 2.6 Regenerate the frontend API client (`scripts/generate-client.sh`) and verify `frontend/src/client` exposes the new bulk-delete service method and types

## 3. Admin selection and bulk action UI

- [ ] 3.1 Add row-selection state (scoped to the current page) to the admin Users table
- [ ] 3.2 Add a per-row checkbox, disabled for the current user's row, and a select-all checkbox limited to the current page and excluding the current user
- [ ] 3.3 Add the always-visible `Delete User(s)` button next to `Add User`, disabled when the selection is empty
- [ ] 3.4 Create `frontend/src/components/Admin/BulkDeleteUsers.tsx` following the `DeleteUser.tsx` dialog pattern: show the selected count and the Item-deletion warning, disable the confirm control and show a spinner while pending, close automatically on response, and show a success or failure toast
- [ ] 3.5 Add frontend tests: row/select-all selection behavior, current-user exclusion, button enable/disable, dialog count and warning text, pending spinner state, success and failure notifications

## 4. Acceptance coverage and completion

- [ ] 4.1 Add page-object and step-definition coverage in `acceptance-tests/support/pages/` for the `admin-bulk-user-delete` scenarios
- [ ] 4.2 Run `npm test` in `acceptance-tests/` and confirm every scenario passes, zero pending/undefined steps, and an HTML report is generated
- [ ] 4.3 Run `npm run lint:specs` in `acceptance-tests/` and fix any reported issues
