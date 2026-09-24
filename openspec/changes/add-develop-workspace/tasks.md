## 1. Domain and persistence

- [ ] 1.1 Add the agreed Development Chat, Development Workspace, Agent Turn, Presence Mode, and Background Mode terms to `CONTEXT.md`
- [ ] 1.2 Add Development Chat and Development Message SQLModel tables, request/response models, relationships, enums, timestamps, JSON activity parts, ownership fields, and proposal decision state
- [ ] 1.3 Add and verify the Alembic migration for chat/message tables, indexes, foreign keys, and cascades
- [ ] 1.4 Add backend model tests for defaults, bounded/validated fields, cascades, and proposal state transitions

## 2. Agent and workspace services

- [ ] 2.1 Port secret scrubbing, session-ID validation, normalized opencode event parsing, tool descriptions, and conversation summarization from AIDev `aidev/api/v1/services/agent.py`
- [ ] 2.2 Add the production command runner and deterministic fake runner with process-group cancellation, stderr draining, timeout, blocking, failure, and scripted event support
- [ ] 2.3 Port `DevelopAgentService` workspace setup and explore/propose/apply behavior, adapting Django settings to Pydantic settings and validating workspace paths before deletion
- [ ] 2.4 Port `TurnConcurrencyGate`, `TurnSession`, and `DevelopTurnManager` from AIDev `agent.py` and `turn_manager.py`, renaming detached mode to background mode
- [ ] 2.5 Add focused backend tests for workspace isolation, credential handling, secret scrubbing, event normalization, session continuity, weighted admission, replay, presence grace, cancellation, timeout, and stop-before-delete ordering

## 3. FastAPI contract

- [ ] 3.1 Add Develop settings for repository credentials, model, workspace root, limits, timeouts, weights, presence grace, fake-runner selection, and safe defaults
- [ ] 3.2 Add ownership-scoped chat collection/detail endpoints for create, list, rename, Presence Mode update, confirmed deletion, and message cursor pagination
- [ ] 3.3 Add repository setup, proposal creation, proposal approval/rejection, explicit stop, streamed turn, and streamed reattachment endpoints
- [ ] 3.4 Register the Develop router, use existing JWT dependencies, and return indistinguishable not-found responses for missing and foreign chats
- [ ] 3.5 Add backend API tests for authentication, ownership, validation, pagination, setup failures, decision conflicts, one-turn-per-chat, and SSE headers/events
- [ ] 3.6 Regenerate `frontend/src/client` from the updated OpenAPI schema and verify Develop JSON operations are typed

## 4. Develop frontend

- [ ] 4.1 Add maintained safe Markdown rendering dependencies and reusable Develop API types, JSON calls, bearer-authenticated SSE parsing, and stream handlers
- [ ] 4.2 Adapt AIDev `DevelopWorkspace.tsx` state, five-chat cache, stream lifecycle, reattachment, optimistic messages, and bounded turn-part handling to target conventions
- [ ] 4.3 Adapt the AIDev history panel with new-chat, recent-chat selection, inline rename, and confirmed permanent deletion interactions
- [ ] 4.4 Adapt the AIDev chat panel with pinned scrolling, incremental history, elapsed time, expandable activity, Stop, Set up repository, Make it happen, Approve, Reject, and Presence Mode controls
- [ ] 4.5 Build the responsive native shadcn Develop layout and reserved context panel without Bootstrap or disabled repository-choice controls
- [ ] 4.6 Add the authenticated `/develop` TanStack route and Develop sidebar item for every authenticated User
- [ ] 4.7 Add Playwright coverage for navigation, responsive layout, chat lifecycle, presence labels, repository setup, streamed activity, proposal decisions, stopping, and deletion confirmation

## 5. Runtime and deployment

- [ ] 5.1 Install and verify `git`, `opencode`, and `openspec` in the backend runtime image using the reference repository's compatible versions where available
- [ ] 5.2 Add persistent Development Workspace volume configuration and documented environment settings without committing credentials
- [ ] 5.3 Change the initial backend runtime to one worker and document the in-process coordination constraint, SSE proxy buffering, heartbeat, and timeout requirements
- [ ] 5.4 Verify production startup rejects unsafe or incomplete Develop configuration with actionable errors while non-Develop test modes remain deterministic

## 6. Acceptance scenarios — each task is red, then green, then committed

- [ ] 6.1 Authenticated user opens Develop — red -> green -> commit
- [ ] 6.2 Unauthenticated client cannot access Develop data — red -> green -> commit
- [ ] 6.3 First message creates a Development Chat — red -> green -> commit
- [ ] 6.4 Recent Development Chats are listed by activity — red -> green -> commit
- [ ] 6.5 User renames a Development Chat — red -> green -> commit
- [ ] 6.6 User cannot access another user's Development Chat — red -> green -> commit
- [ ] 6.7 Older messages are loaded incrementally — red -> green -> commit
- [ ] 6.8 User sets up the configured repository — red -> green -> commit
- [ ] 6.9 Repository setup is unavailable when configuration is missing — red -> green -> commit
- [ ] 6.10 Development Workspaces are isolated — red -> green -> commit
- [ ] 6.11 User explores a ready repository — red -> green -> commit
- [ ] 6.12 User reattaches to an active Agent Turn — red -> green -> commit
- [ ] 6.13 Concurrent turn for one chat is rejected — red -> green -> commit
- [ ] 6.14 User explicitly stops an Agent Turn — red -> green -> commit
- [ ] 6.15 User requests a proposal — red -> green -> commit
- [ ] 6.16 User approves a proposal — red -> green -> commit
- [ ] 6.17 User rejects a proposal — red -> green -> commit
- [ ] 6.18 Stop when I leave cancels after the grace period — red -> green -> commit
- [ ] 6.19 Reattachment within the grace period preserves the turn — red -> green -> commit
- [ ] 6.20 Continue in background survives disconnection — red -> green -> commit
- [ ] 6.21 Background turn limit is enforced per user — red -> green -> commit
- [ ] 6.22 Agent Turn waits for capacity — red -> green -> commit
- [ ] 6.23 Agent Turn times out — red -> green -> commit
- [ ] 6.24 Agent output contains a configured secret — red -> green -> commit
- [ ] 6.25 User cancels Development Chat deletion — red -> green -> commit
- [ ] 6.26 User confirms Development Chat deletion — red -> green -> commit

## 7. Completion

- [ ] 7.1 Run backend tests and static checks; fix only Develop regressions
- [ ] 7.2 Run frontend build, formatting checks, and Playwright tests; fix only Develop regressions
- [ ] 7.3 Run `npm --prefix acceptance-tests run lint:specs` and confirm all extracted Gherkin remains clean
- [ ] 7.4 Run `npm --prefix acceptance-tests test`; every scenario passes with zero pending or undefined steps and the HTML report is generated
- [ ] 7.5 Compare implemented behavior against the AIDev source-to-target checklist and confirm no runtime dependency on `/Users/wpan862@cable.comcast.com/workspace/wu/AIDev`