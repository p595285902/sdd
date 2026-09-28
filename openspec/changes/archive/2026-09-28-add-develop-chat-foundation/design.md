## Context

The application separates a FastAPI/SQLModel backend from a Vite/React frontend, authenticates API requests with bearer JWTs, and generates its typed frontend client from OpenAPI. It currently has no persistent development conversations. This change establishes only the chat foundation needed by later workspace and agent changes.

The committed history of the superseded `add-develop-workspace` change remains the detailed source for drafting each named successor, including the AIDev reference paths, orchestration decisions, runtime constraints, and deferred scenarios.

Development Chat means a User-owned persistent conversation. Development Message means one ordered user or assistant entry in that conversation. Repository setup, agent sessions, activity parts, proposal decisions, and long-lived streams remain outside this change.

## Goals / Non-Goals

**Goals:**

- Persist Development Chats and Development Messages with ownership enforced at the query boundary.
- Provide bounded recent-chat listing and cursor-based message pagination.
- Expose the smallest authenticated Develop UI needed to create, select, and rename chats.
- Keep missing and foreign chat responses indistinguishable.

**Non-Goals:**

- Creating or deleting repository workspaces.
- Running external commands or agents.
- Streaming events, handling presence, or coordinating background work.
- Generating or applying proposals.
- Delivering the final three-column Develop interface.

## Decisions

### Persist chats and messages with ownership at the query boundary

Add SQLModel tables for Development Chats and Development Messages. A chat belongs to one User and stores its title and activity timestamps. A message belongs to one chat and stores its role, text content, and creation time. Deleting a User cascades to their chats and messages.

Every chat lookup includes both chat ID and current User ID. A missing or foreign chat returns the same not-found response. This avoids relying on a later authorization check that could disclose another User's resource.

Alternative considered: process-memory or workspace-file history. That would lose conversations across restarts and make ownership and pagination inconsistent.

### Create the chat atomically with its first message

The new-chat UI remains client-local until the User submits nonempty text. One backend transaction creates the chat and first message, avoiding empty persisted chats and partial first-message failures.

Alternative considered: create a chat when the route opens. That creates abandoned empty records and complicates recent-chat ordering.

### Use stable cursor pagination and separate activity from renaming

Messages use `(created_at, id)` cursor ordering and accept either `before` or `after`, never both. Responses are returned in conversation order. Recent chats are ordered by `(updated_at, id)` and bounded by explicit history and page-size settings.

Renaming uses a direct title update that does not alter `updated_at`; message creation updates chat activity. This preserves the requirement that rename not reorder history.

Alternative considered: offset pagination. Concurrent inserts can duplicate or skip records between pages.

### Keep the first frontend deliberately small

Add the protected `/develop` route and authenticated sidebar entry with a minimal chat list and conversation surface. Use the generated client for all JSON requests. Later changes replace this shell with the complete responsive interface after workspace and streaming contracts exist.

Alternative considered: build the final interface now. That would couple this foundation to APIs and states intentionally deferred to successor changes.

## Risks / Trade-offs

- [The temporary UI will be replaced later] -> Keep it small and use existing route, component, and generated-client conventions.
- [Timestamp ties could make ordering unstable] -> Include the record ID in every cursor and ordering tuple.
- [A rename could accidentally reorder chats through ORM timestamp hooks] -> Use a focused update path and test unchanged activity ordering.
- [Later message kinds require schema expansion] -> Keep this initial message model intentionally narrow and add agent-specific fields in their owning changes.

## Migration Plan

1. Add the chat and message tables, indexes, foreign keys, and cascades.
2. Add ownership-scoped JSON endpoints and regenerate the frontend client.
3. Add the minimal route, navigation, and chat lifecycle UI.
4. Implement the seven acceptance scenarios and run the complete effective suite.
5. Archive this change before scaffolding `add-develop-workspace-setup`; continue through the successor sequence recorded in the proposal one active delta at a time.

Rollback removes the route and API registration before rolling back the additive migration. No repository workspace or external process cleanup is involved.

## Open Questions

None.
