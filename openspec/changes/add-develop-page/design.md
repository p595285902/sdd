## Context

The repository is a FastAPI + SQLModel + PostgreSQL backend with a React 19, TanStack Router, Tailwind, and shadcn/ui frontend. The frontend is built into the backend image and served from the same origin; the API lives under `/api/v1` and the frontend client is generated from the OpenAPI document. Authentication uses a JWT in `localStorage`, and pages under the `_layout` route require a session.

This branch has no Develop page, no conversation tables, and no tracked acceptance runner. The acceptance framework is the behavior-driven OpenSpec workflow: Markdown specs with fenced Gherkin, extracted to features and run by cucumber-js (`stack: javascript`), with Playwright needed for browser behavior. The change must leave `openspec/` and code changes in separate commits.

## Goals / Non-Goals

**Goals:**

- Deliver an end-to-end Develop page: three-panel layout, user-owned persistent chats, paginated history, message exchange, and a streamed mocked Markdown reply.
- Keep conversations server-owned so clearing browser data and logging in again preserves them.
- Stand up the project's JavaScript acceptance suite with Playwright browser coverage, running against a fresh full Docker Compose stack per suite run.

**Non-Goals:**

- Real agent integration, tool calls, or repository workspaces.
- Message pagination, message editing, or message deletion.
- Mobile/responsive controls, Context panel content, login redirect-back, and CI workflow changes.
- A separate pytest suite for the new API (the acceptance suite is the gate).

## Decisions

### Backend persistence instead of browser storage

Development Chats and Messages live in PostgreSQL, not `localStorage` or in-memory state. The spec requires ownership isolation, history pagination, and survival after clearing browser data; those are server concerns, and a future real agent needs a durable conversation. Alternatives considered: `localStorage` (lost on site-data clear, no ownership) and in-memory (lost on reload).

### Data model

- `development_chat`: `id` UUID PK, `owner_id` UUID FK → `user.id` with `ON DELETE CASCADE`, `title` varchar(255) not null, `created_at` timestamptz, `last_activity_at` timestamptz (defaults to creation and is updated when a message is stored). Index on `(owner_id, last_activity_at DESC)`.
- `development_message`: `id` UUID PK, `chat_id` UUID FK → `development_chat.id` with `ON DELETE CASCADE`, `role` varchar constrained to `user` / `assistant`, `content` text, `created_at` timestamptz. Index on `(chat_id, created_at)`.
- Ordering: chats by `last_activity_at DESC, id DESC`; messages by `created_at ASC, id ASC`. Renaming does not change `last_activity_at`.
- SQLModel relationships mirror the existing `User`/`Item` pattern (`cascade_delete=True`) so ORM and database deletes both cascade. A new Alembic revision creates both tables and indexes.

### REST API under `/api/v1/develop`

All routes require the current authenticated user; requests for another user's chat return **404** so existence is not revealed.

| Method | Path | Behavior |
|---|---|---|
| `GET` | `/chats?skip=0&limit=10` | Owner's chats, most recent activity first, plus `count`. Offset pagination matches the Items API. |
| `POST` | `/chats` | Body `{message}`. Creates the chat, derives the title from the first message (whitespace-normalized, 60 chars), stores the first user message, and returns the chat plus the stored message. Non-streaming so tests can seed quickly. |
| `GET` | `/chats/{chat_id}` | Owner's chat detail. |
| `PATCH` | `/chats/{chat_id}` | Body `{title}`. Trims and rejects empty titles; does not reorder. |
| `DELETE` | `/chats/{chat_id}` | Deletes the chat and cascades its messages. |
| `GET` | `/chats/{chat_id}/messages` | All messages oldest first. |
| `POST` | `/chats/{chat_id}/messages` | Body `{message}`. Stores a user message and returns it. |
| `POST` | `/chats/{chat_id}/turns` | Body `{message_id}`. Validates the user message belongs to the chat, then streams the mocked assistant reply over SSE. Stores the assistant message when the stream completes and updates `last_activity_at`. |

Separating message storage from the reply stream keeps both endpoints simple and makes the user message durable before the two-second mock runs. The frontend calls store-then-turn; a failed or interrupted turn leaves the user message and no assistant message, which matches the agreed behavior.

### Streaming protocol

The turn endpoint returns `text/event-stream` with `event: chunk` events carrying `{"text": "..."}` and a final `event: done` carrying the stored assistant message. Chunks are `# header\n\n`, `2nd message\n\n`, and `## small header`, separated by roughly 0.65 seconds so the whole reply completes in about two seconds. The assistant content stored is their concatenation.

The stream generator writes the final message through a fresh SQLModel `Session` rather than the request-scoped session, because dependency cleanup can race with a long-lived streaming response. The mock lives in a small service module so a real agent can replace the generator later.

### Frontend route and data flow

- File routes: `src/routes/_layout/develop.tsx` (parent, renders the three panels and an `<Outlet/>`) and `src/routes/_layout/develop.$chatId.tsx` (child, renders the selected conversation). `/develop` shows the "select a chat" empty state; `/develop/<id>` restores that chat from the URL. The generated `routeTree.gen.ts` is regenerated.
- The sidebar `Main` active check is extended to prefix matching so Develop stays highlighted on `/develop/<id>`.
- TanStack Query: an infinite query for chat history (page size 10, next page while loaded < `count`), a query for the selected chat, and a query for its messages. Create, rename, delete, send, and reply completion invalidate the relevant keys.
- After the first message creates a chat, the page navigates to `/develop/<id>`. After deleting the open chat, it navigates to `/develop` without selecting a replacement. Clicking "New chat" goes to `/develop`.
- The composer is a textarea: Enter sends, Shift+Enter inserts a newline; the send control has the same effect. It is disabled for empty/whitespace input and while a reply streams.
- Streaming is handled with `fetch` + `ReadableStream` (manual SSE parsing) because the generated axios client does not model this POST stream; the bearer token is read from `localStorage`, matching the existing client. An `AbortController` cancels the turn when the chat changes or the page unmounts. The user message is appended to the query cache as soon as the store call returns.
- `react-markdown` renders assistant content with custom `h1`, `h2`, and `p` components; raw HTML stays disabled. User messages align right, assistant messages left. A `role="status"` element with "Responding…" is shown while chunks arrive.
- Accessibility identifiers for the acceptance page objects: nav link "Develop", history `nav` labelled "Chat history", "New chat" button, per-row delete control labelled with the chat title, "Rename chat" control and dialog with "Chat title" input, message textarea labelled "Message", "Send message" control, and the "Responding…" status.

### Acceptance suite

`acceptance-tests/` is an independent npm project using cucumber-js, Playwright, glob, cheerio, and gherkin-lint. The skill's reference extractor, `cucumber.cjs`, `openspec-effective-paths.cjs`, and `.gherkin-lintrc` are copied verbatim, so extraction, effective-spec composition, archive exclusion, and source-of-truth-only runs behave exactly as the skill defines.

The hooks run on the host and own one fresh stack per suite invocation:

1. Reserve a free local port and a unique Compose project name.
2. `docker compose -p <project> -f compose.yml -f acceptance-tests/compose.yml up --build -d db`
3. `docker compose ... run --rm backend bash scripts/prestart.sh` (migrations + first superuser)
4. `docker compose ... up --build -d --wait backend`, then poll `/api/v1/utils/health-check/`
5. Launch headless Chromium; `AfterAll` runs `docker compose ... down --volumes --remove-orphans` and prints backend logs on failure.

`acceptance-tests/compose.yml` overrides the root compose for the test stack: backend runs `fastapi run --workers 1`, publishes `127.0.0.1:${ACCEPTANCE_PORT}:8000`, healthchecks port 8000, and supplies the required project, database, superuser, SMTP, and `FRONTEND_HOST` values. The backend image already builds and serves the frontend, so no separate Vite server or Traefik is involved. Only `db` and `backend` are started.

The World holds a thin HTTP client (register users, obtain tokens, seed chats/messages, ownership requests) and a Playwright page/context. Page objects live in `acceptance-tests/support/pages/`: a Develop page and a login page. Each scenario uses a unique user and unique chats, so the single stack needs no per-scenario reset endpoint. The browser gets the token through an init script; the clearing-site-data scenario empties storage and logs in through the login page. Twenty-five chats are seeded through `POST /develop/chats`, which does not stream.

## Risks / Trade-offs

- **Streaming response session lifecycle** → the generator uses its own `Session` and writes only on completion; ownership is validated before the stream starts.
- **Client disconnects mid-stream** → the reply is not stored; this is accepted and matches the mid-stream refresh rule. The user message remains.
- **SSE is not covered by the generated client** → a small typed fetch helper owns parsing, token handling, and aborting; the backend schema documents `text/event-stream`.
- **Exact two-second timing is brittle in tests** → acceptance asserts the responding status appears and then clears plus the final Markdown, not a millisecond budget.
- **Offset pagination can shift when a new chat is created while scrolling** → acceptable for a single-user history; the history refetches after sends and creates.
- **Infinite-scroll double fetches** → guard on `isFetchingNextPage` and `hasNextPage`, with an IntersectionObserver sentinel.
- **Docker build time and port collisions** → dynamic free port, unique project name, build cache, and serial scenarios.
- **Clearing site data logs the user out** → explicit by design; the acceptance scenario logs in again and then verifies the server-owned conversation.
- **`react-markdown` bundle size** → accepted for correct Markdown rendering; no raw-HTML plugin.
- **The root `compose.override.yml` is not loaded when explicit `-f` files are used** → the acceptance override supplies every setting the test stack needs.
- **The default acceptance run has only a delta spec until sync** → the delta scenarios are the red work list; the source-of-truth-only profile is empty until the change is synced.

## Migration Plan

- Add one Alembic revision creating `development_chat` and `development_message` with foreign keys, cascade rules, and indexes. `scripts/prestart.sh` applies it on every start.
- Deploy adds tables only; no existing table is altered. Rollback is `alembic downgrade -1`, which drops the new tables (data loss is limited to Develop conversations).
- The frontend is rebuilt into the backend image; no separate deployment step. Acceptance stacks start from fresh volumes, so they always exercise the migration.

## Open Questions

None — scope, terminology, persistence, streaming, and test boundaries were settled during grilling.
