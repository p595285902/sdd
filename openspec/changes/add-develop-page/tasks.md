## 1. First-time acceptance setup

- [ ] 1.1 Verify `stack: javascript` is recorded in `openspec/config.yaml` and was committed on its own (already done in the specs zone)
- [ ] 1.2 Add `acceptance-tests/compose.yml` as an override of the root `compose.yml`: backend runs `fastapi run --workers 1`, publishes `127.0.0.1:${ACCEPTANCE_PORT}:8000`, healthchecks port 8000, `db` exposes no host port, and all required project, database, superuser, SMTP, and `FRONTEND_HOST` values are supplied
- [ ] 1.3 Create `acceptance-tests/package.json` as an independent npm project with `@cucumber/cucumber`, `@playwright/test`, `glob`, `cheerio`, and `gherkin-lint`, and scripts `test`, `test:specs`, and `lint:specs`
- [ ] 1.4 Copy the reference files verbatim: `.claude/skills/acceptance-test-authoring/references/javascript/extract-gherkin.cjs` → `acceptance-tests/extract-gherkin.cjs`, `.../javascript/cucumber.cjs` → `acceptance-tests/cucumber.cjs`, `.../javascript/openspec-effective-paths.cjs` → `acceptance-tests/openspec-effective-paths.cjs`, and `.../references/gherkin-lintrc.json` → `acceptance-tests/.gherkin-lintrc`
- [ ] 1.5 Implement `acceptance-tests/features/support/app-lifecycle.js`, `world.js`, and `hooks.js`: unique Compose project and free port, `up db`, `prestart.sh`, `up backend --wait`, health polling, headless Chromium, final `down --volumes --remove-orphans`, and backend logs on failure
- [ ] 1.6 Make the single test command always generate `acceptance-tests/reports/cucumber-report.html`, add the spec-lint command, and confirm the root `.gitignore` covers `acceptance-tests/.extracted/`, `acceptance-tests/reports/`, and `acceptance-tests/node_modules/`
- [ ] 1.7 Write `acceptance-tests/README.md` with install, `npx playwright install chromium`, Docker prerequisite, run commands, and the HTML report location
- [ ] 1.8 Verify extraction and composition: the effective dry run discovers the 16 delta scenarios, no archive scenario, and `npm --prefix acceptance-tests run lint:specs` passes

## 2. Backend data and API

- [ ] 2.1 Add Development Chat, Development Message, and Development Conversation terms to `CONTEXT.md`
- [ ] 2.2 Add `DevelopmentChat` and `DevelopmentMessage` SQLModel models with ownership, cascade deletion, timestamps, roles, content, and ordering indexes
- [ ] 2.3 Add one Alembic revision creating `development_chat` and `development_message` with foreign keys, cascades, and indexes
- [ ] 2.4 Add request/response models for chats and messages, title normalization/truncation, and bounded validation
- [ ] 2.5 Add owner-scoped chat endpoints: list with `skip`/`limit` and `count`, create with first message, detail, rename, and delete, returning 404 for missing or foreign chats
- [ ] 2.6 Add owner-scoped message endpoints: list oldest first and create a user message (updating chat activity)
- [ ] 2.7 Add the SSE turn endpoint and mock reply service: validate the user message, emit three chunks over ~2 seconds, store the assistant message on completion, and update activity
- [ ] 2.8 Register the Develop router and regenerate `frontend/src/client` from the updated OpenAPI schema

## 3. Frontend Develop page

- [ ] 3.1 Add `react-markdown` to `frontend/package.json`
- [ ] 3.2 Add `frontend/src/routes/_layout/develop.tsx` and `develop.$chatId.tsx`, add the Develop sidebar item, and make the sidebar active check match nested paths
- [ ] 3.3 Build the three-panel desktop layout: chat history with New chat and per-row delete, chat header with title and rename, scrollable conversation, composer, and empty Context panel
- [ ] 3.4 Add TanStack Query hooks for the infinite chat list, selected chat, and messages, plus create, rename, and delete mutations with invalidation
- [ ] 3.5 Implement sending: textarea with Enter send and Shift+Enter newline, send control, store-message call, SSE turn stream with abort, optimistic user message, and disabled empty/streaming composer
- [ ] 3.6 Render user messages right, assistant messages left, Markdown via `react-markdown`, and the accessible "Responding…" status while streaming
- [ ] 3.7 Add empty states for no chats and no selected chat, delete confirmation dialogs, and navigation to `/develop` after deleting the open chat
- [ ] 3.8 Run the frontend typecheck/build and fix Develop regressions

## 4. Acceptance scenarios — each task is red → green → commit

- [ ] 4.1 Authenticated user opens Develop — red → green → commit
- [ ] 4.2 Unauthenticated visitor cannot open Develop — red → green → commit
- [ ] 4.3 First message creates a Development Chat — red → green → commit
- [ ] 4.4 Unsent draft is not stored — red → green → commit
- [ ] 4.5 Owner renames a Development Chat — red → green → commit
- [ ] 4.6 Owner deletes a Development Chat — red → green → commit
- [ ] 4.7 Deleting the open chat clears the chat panel — red → green → commit
- [ ] 4.8 User cannot access another user's chat — red → green → commit
- [ ] 4.9 Development Conversation survives clearing browser data — red → green → commit
- [ ] 4.10 Ten most recent chats are listed — red → green → commit
- [ ] 4.11 Scrolling to the end loads older chats — red → green → commit
- [ ] 4.12 Empty chat history shows an empty state — red → green → commit
- [ ] 4.13 User sends messages with both controls — red → green → commit
- [ ] 4.14 Assistant reply streams and renders Markdown — red → green → commit
- [ ] 4.15 Composer rejects invalid sends and blocks sends during a reply — red → green → commit
- [ ] 4.16 Opening a chat URL displays its conversation — red → green → commit

## 5. Completion

- [ ] 5.1 Run the existing backend test suite and fix only regressions introduced by this change
- [ ] 5.2 Run the frontend lint/build and fix only Develop regressions
- [ ] 5.3 Run `npm --prefix acceptance-tests run lint:specs` with no issues
- [ ] 5.4 Run `npm --prefix acceptance-tests test`: every scenario passes with zero pending or undefined steps, the HTML report is generated, and the source-of-truth-only profile runs cleanly
- [ ] 5.5 Review the final diff: `CONTEXT.md`, generated client, migration, route tree, and acceptance runner are included; `openspec/` and code are committed separately
