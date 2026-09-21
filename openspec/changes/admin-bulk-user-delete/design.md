## Context

The admin page currently loads users into the shared TanStack `DataTable`, whose pagination and table state are internal, and exposes only per-row edit and delete actions. The backend deletes one user per request after a superuser check, explicitly removes that user's Items, and commits immediately. Bulk deletion crosses the admin route, reusable table API, generated OpenAPI client, FastAPI route and models, and transaction handling.

The current superuser must remain unselectable in the UI and protected by the API. The API is the security boundary: it must validate the complete request before mutating data, because UI constraints can be bypassed. No schema migration or new dependency is required.

## Goals / Non-Goals

**Goals:**

- Support accessible per-row and current-page selection without allowing selection of the signed-in user.
- Keep the bulk action next to `Add User` and represent idle, confirmation, pending, success, and failure states.
- Delete all requested users and their Items in one transaction, or delete nothing.
- Expose the operation through the OpenAPI schema and generated frontend client.

**Non-Goals:**

- Selecting every user across all server or client pagination pages.
- Replacing the existing single-user delete flow.
- Adding soft deletion, undo, background jobs, or database migrations.
- Changing user-list pagination or introducing a general bulk-action framework.

## Decisions

### Use a dedicated static bulk-delete route

Add an authenticated-superuser `POST /users/bulk-delete` endpoint with a request model containing a non-empty list of user UUIDs and a `Message` response. Declare the static route before `/{user_id}` routes so `bulk-delete` cannot be consumed as a dynamic UUID path. `POST` is preferred over a request body on `DELETE` because client and intermediary support for DELETE bodies is inconsistent, while the operation remains explicitly named and destructive.

Alternative considered: issue one existing delete request per selected user. This cannot guarantee all-or-nothing behavior and produces partial success when any request fails.

### Validate the complete target set before mutation

Normalize duplicate IDs, reject an empty request at model validation, fetch all target users in one query, and compare the returned ID set with the requested set. Reject the request if any ID is missing or if the current user's ID is present. Only after all checks pass will the route delete Items owned by the targets, delete the users, and commit once.

The existing explicit Item deletion behavior will be applied to the full target set before deleting users. Both statements and the single commit use the same session transaction; validation errors occur before either statement. Unexpected database errors are left uncommitted so session cleanup can roll back the transaction.

Alternative considered: validate and delete each user in a loop. Even with one final commit, interleaving validation and mutation obscures the atomicity guarantee and can leave the session with pending partial changes before a later invalid target is found.

### Keep authorization and self-protection on the server

Reuse `get_current_active_superuser` for the new route and compare requested UUIDs with `current_user.id`. The disabled current-user checkbox is a usability guard, not an authorization control. A non-superuser, nonexistent target, or self-target rejects the whole request without deleting users or Items.

Alternative considered: rely on the admin route guard and disabled checkbox. Direct API calls would bypass both controls.

### Add controlled row selection to the shared table

Extend `DataTable` with the minimal TanStack row-selection inputs needed by the admin page: stable row IDs, controlled selection state/change handling, and an eligibility predicate. The admin columns add an accessible checkbox column using current-page selection APIs for the header and row selection APIs for cells. The current user's row fails the eligibility predicate and therefore renders disabled.

Selection state is owned by the admin page and keyed by user UUID, allowing the header action and table to share one source of truth. The header checkbox uses the current-page toggle APIs, so changing pages does not select rows on other pages. Selection is cleared after successful deletion.

Alternative considered: create an admin-only table or track checkbox state separately from TanStack Table. Either duplicates pagination behavior or risks disagreement between visible-page state and selected IDs.

### Isolate confirmation and mutation behavior in a bulk action component

Add a bulk-delete component beside `Add User`. It receives selected UUIDs, remains visible while disabled for an empty selection, and owns the confirmation dialog and mutation. The dialog interpolates the selected count and reuses the permanent Item deletion warning. The existing `LoadingButton` supplies disabled and spinner behavior while pending. Success closes the dialog, clears selection, invalidates the users query, and shows a success toast; errors show the existing error toast path, and settlement closes the dialog after the response.

Alternative considered: reuse the row-level `DeleteUser` component. Its single-ID contract and dropdown trigger would couple two distinct interaction flows and make count-based confirmation and selection cleanup awkward.

### Drive client-rendered acceptance scenarios with Playwright

Keep `acceptance-tests/` as an independent Cucumber project and include `@playwright/test` as its browser driver. Use Playwright-backed page objects for the client-rendered admin UI and `cheerio` only for HTTP responses that can be inspected without executing JavaScript. This keeps selectors, routes, and browser operations out of step definitions while allowing the executable Gherkin scenarios to exercise the real React application.

Alternative considered: import Playwright from `frontend/node_modules`. That couples the independent acceptance project to another package's installation layout and dependency lifecycle. An API-only suite cannot implement the specified UI scenarios.

### Regenerate the client from the backend OpenAPI document

After adding the backend model and route, regenerate `frontend/src/client` with the existing OpenAPI generation workflow. Frontend code will call the generated service method rather than hand-writing an HTTP request, keeping request and response types aligned with the backend contract.

## Risks / Trade-offs

- [Selection can become stale after query refresh] -> Clear selection after successful deletion and ignore IDs not represented by current data when rendering.
- [A static route can conflict with the dynamic UUID route] -> Declare `/bulk-delete` before `/{user_id}` and cover routing with an endpoint test.
- [Large ID lists create large SQL `IN` clauses] -> The UI currently loads at most 100 users and selection is page-scoped; enforce a bounded request size if that list limit changes.
- [Bulk SQL deletes bypass ORM relationship behavior] -> Explicitly delete matching Items first, mirroring the existing endpoint, and verify cascade outcomes in backend tests.
- [Generic `DataTable` API grows for one consumer] -> Add only standard controlled-selection hooks and leave defaults unchanged for existing tables.

## Migration Plan

1. Add and test the backend request model and bulk endpoint.
2. Regenerate the OpenAPI client so the frontend receives the typed service method.
3. Add controlled table selection, the checkbox column, and the bulk confirmation component.
4. Run backend, frontend, and effective acceptance suites before deployment.

Deployment requires no database migration. Rollback consists of reverting the frontend action and backend route; existing single-user deletion remains available throughout.

## Open Questions

None. The current 100-user fetch bounds the initial request size, and current-page selection defines the supported scope.