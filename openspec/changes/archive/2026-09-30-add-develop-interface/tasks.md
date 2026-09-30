## 1. Workspace state and components

- [x] 1.1 Add maintained safe Markdown rendering with raw HTML disabled
- [x] 1.2 Adapt DevelopWorkspace state for a bounded five-chat cache, optimistic messages, replay deduplication, and stream lifecycle
- [x] 1.3 Build chat history interactions for new chat, selection, inline rename, incremental history, and confirmed deletion
- [x] 1.4 Build conversation interactions for setup, pinned scrolling, elapsed time, expandable activity, Stop, and Presence Mode
- [x] 1.5 Build the unframed responsive history, conversation, and context layout with narrow-screen controls

## 2. Frontend integration and tests

- [x] 2.1 Replace the foundation shell while preserving the authenticated route and sidebar entry
- [x] 2.2 Add component tests for cache bounds, optimistic reconciliation, stream replay, Markdown safety, and control state
- [x] 2.3 Add Playwright coverage for desktop and mobile layout, chat lifecycle, setup, stream rendering, presence labels, stop, and deletion confirmation

## 3. Acceptance scenario — red, then green, then committed

- [x] 3.1 Streamed exploration is displayed — red -> green -> commit

## 4. Completion

- [x] 4.1 Run frontend formatting, type checks, build, component tests, and Playwright tests
- [x] 4.2 Run spec lint and the full effective acceptance suite with zero pending or undefined steps
