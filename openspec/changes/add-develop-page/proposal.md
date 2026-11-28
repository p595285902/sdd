## Why

Authenticated users need a Develop page where they can hold persistent conversations with the assistant. The app currently has no Develop page, no conversation storage, and no streaming contract. The assistant reply is mocked for now so the page, persistence, and streaming behavior can be built and acceptance-tested before a real agent is connected.

## What Changes

- Add an authenticated `/develop` page with three panels: chat history (left), chat (middle), and an empty Context panel (right).
- Persist user-owned Development Chats and Development Messages in PostgreSQL, exposed through REST endpoints and the generated frontend client.
- Create a Development Chat from its first message, auto-title it from that message, rename it, delete it, and list chats by most recent activity in pages of ten.
- Send messages and stream a mocked Markdown reply over SSE — `# header`, `2nd message`, `## small header` over roughly two seconds — rendered progressively with `react-markdown`.
- Keep the selected chat in the URL so a reload restores it, and keep conversations server-owned so clearing browser data and logging in again preserves them.
- Scaffold the JavaScript cucumber-js acceptance project with Playwright browser coverage, running against a fresh full Docker Compose stack per suite run.
- Record the Development Chat, Development Message, and Development Conversation terms in `CONTEXT.md`.

No breaking changes.

## Capabilities

### New Capabilities

- `develop-chat`: authenticated Develop page, user-owned Development Chat lifecycle, paginated chat history, message exchange, streamed Markdown replies, and the empty Context panel.

### Modified Capabilities

None.

## Impact

- **Backend**: new SQLModel tables and an Alembic migration for chats and messages; new `/api/v1/develop` routes with ownership enforcement; an SSE message-reply endpoint; regenerated frontend client.
- **Frontend**: new `/develop/$chatId` route and sidebar entry; three-panel page; React Query data hooks; `react-markdown` dependency.
- **Acceptance**: new `acceptance-tests/` JavaScript project, `acceptance-tests/compose.yml` override, Playwright page objects and step definitions, and an HTML report. The root `compose.yml` is reused under a unique project name.
- **Docs**: `CONTEXT.md` glossary.
- **Excluded**: real agent integration, message pagination, mobile layout, Context panel content, login redirect-back, CI workflow changes.
