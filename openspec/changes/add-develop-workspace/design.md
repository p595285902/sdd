## Context

The target application separates a FastAPI/SQLModel backend from a Vite/React frontend, authenticates API requests with bearer JWTs, generates its typed frontend client from OpenAPI, and currently runs four FastAPI worker processes. It has no chat persistence, long-lived server stream, per-user repository workspace, or agent-process manager.

The reference implementation is `/Users/wpan862@cable.comcast.com/workspace/wu/AIDev`. Its Develop page begins at `aidev/templates/pages/develop.html`; the behavior is primarily implemented by:

- `aidev/static/js/develop/DevelopWorkspace.tsx`, `api.ts`, `types.ts`, and `components/*`
- `aidev/api/v1/develop/views.py` and `urls.py`
- `aidev/api/v1/services/agent.py` and `turn_manager.py`
- `aidev/users/models.py`

The implementation should reuse those algorithms and interaction semantics where they fit, but port them into the target application's frameworks and conventions. The target must not import from or require the AIDev checkout at runtime.

Development Chat means a User-owned persistent conversation and agent session. Development Workspace means its isolated repository checkout. Agent Turn means one explore, propose, or apply operation. Presence Mode means the policy governing whether an Agent Turn survives client disconnection; its values are presented as `Stop when I leave` and `Continue in background`.

## Goals / Non-Goals

**Goals:**

- Preserve AIDev's complete Develop workflow and lifecycle semantics in the target stack.
- Reuse the reference agent orchestration, event normalization, secret scrubbing, weighted admission, event buffering, presence grace, and session-continuity logic where practical.
- Keep every chat, message, session, process, and workspace scoped to its owning User.
- Present a native shadcn/TanStack interface rather than transplanting Django templates or Bootstrap.
- Make external CLI behavior deterministic and replaceable in automated tests.

**Non-Goals:**

- Selecting arbitrary repositories or storing per-user repository credentials.
- Running turns across multiple backend processes or hosts.
- Publishing workspace changes, pushing branches, or creating pull requests.
- Replacing `opencode`, `openspec`, or OpenAI with a provider-neutral agent framework.
- Providing shared chats, collaborative editing, or administrator access to another User's chats.

## Decisions

### Port behavior, not framework-specific source structure

Use the AIDev implementation as the behavioral and algorithmic reference. Port `DevelopAgentService`, `TurnConcurrencyGate`, `DevelopTurnManager`, normalized turn events, bounded turn parts, pagination, and frontend state transitions. Adapt Django ORM and REST views to SQLModel and FastAPI, Django settings to Pydantic settings, session/CSRF authentication to existing bearer JWT dependencies, and Webpack/Bootstrap components to the existing Vite/shadcn application.

Keep a source-to-target checklist in implementation tasks so omissions are visible. Do not copy Django response wrappers, model APIs, template mounting, CSRF handling, or Bootstrap markup.

Alternative considered: redesign the feature from requirements alone. That would discard tested lifecycle details the user explicitly asked to reuse and increase behavioral drift.

### Persist chats and messages with ownership at the query boundary

Add SQLModel tables for Development Chats and Development Messages. A chat belongs to one User and stores its title, Presence Mode, optional validated `opencode` session ID, and activity timestamps. A message belongs to one chat and stores role, semantic kind, text content, optional proposal decision, bounded JSON activity parts, and creation time. Deleting a User or chat cascades to its messages.

All chat lookups include both chat ID and current User ID. A missing or foreign chat uses the same not-found response so ownership is not disclosed. Cursor pagination follows AIDev's `(created_at, id)` ordering and supports either `before` or `after`, never both. Renaming uses a direct update that does not change activity ordering.

Alternative considered: keep conversations only in process memory or workspace files. That loses history across restarts and makes ownership, pagination, and deletion harder to enforce consistently.

### Expose resource APIs plus bearer-authenticated SSE streams

Add an authenticated FastAPI router under `/api/v1/develop` for chat collection/detail, messages, repository setup, proposal creation, turn streaming/reattachment, approve, reject, and stop operations. Ordinary JSON endpoints are represented in OpenAPI and consumed through the generated client.

Use `StreamingResponse` with `text/event-stream`, no-cache headers, proxy-buffering disabled, 15-second heartbeats, and normalized `session`, `status`, `text`, `error`, `idle`, and `done` events. The frontend consumes streams with `fetch` and an `Authorization: Bearer` header because browser `EventSource` cannot attach the existing bearer token. A small SSE parser lives in the Develop API adapter; it is the only hand-written transport path.

Alternative considered: WebSockets. AIDev's one-way event stream already matches SSE, and introducing a second bidirectional protocol adds infrastructure without a requirement.

### Reuse AIDev agent orchestration behind a narrow command runner

Port `DevelopAgentService` from `aidev/api/v1/services/agent.py`, including:

- one workspace directory per chat under a configured root
- tokenless clone URLs and environment-backed Git credentials
- `opencode init` followed by `openspec init --tools opencode`
- `/openspec explore`, `/openspec propose`, and `/openspec apply` prompts
- newline-delimited JSON parsing and event normalization
- validated `ses_...` session reuse
- process groups, stderr draining, timeout cancellation, and secret scrubbing
- weighted turn admission and bounded activity parts

Extract subprocess creation/execution behind a command-runner protocol. Production uses real processes; backend and acceptance tests use a deterministic fake runner that emits representative opencode events and supports blocking, failure, timeout, and cancellation. This preserves the ported orchestration while avoiding network, GitHub, and model dependencies in tests.

Use `DEVELOP_AGENT_MODEL` with default `openai/gpt-5.4-mini`. Other settings cover repository URL/token, OpenAI key, workspace root, timeouts, history/page/part limits, presence grace, concurrency capacity/weights, and per-user background-turn limit.

Alternative considered: call an LLM API directly. That would not reuse the requested OpenCode/OpenSpec workflow or its repository tools and session behavior.

### Keep turn coordination in one backend process

Port `DevelopTurnManager` and `TurnSession` from AIDev: daemon-thread execution, buffered replay, subscriber tracking, grace timers, one active turn per chat, per-user background-turn counting, weighted global capacity, and completion persistence. Rename the internal source value `detached` to `background` while presenting `Continue in background` in the UI.

Because this state is process-local, run the initial deployment with one FastAPI worker. Update the container command and deployment documentation accordingly. Multi-process or multi-host operation requires a later durable coordinator, shared event log, distributed admission control, and shared workspace storage.

Alternative considered: retain four workers and accept process-local routing. Requests could land on different workers, making reattachment, stopping, limits, and presence cancellation incorrect.

### Delete workspaces with path validation and stop-before-delete ordering

When deletion is confirmed, authorize ownership, stop any active Agent Turn, wait for process termination within a bounded interval, and then remove persistence and workspace state. Resolve both the configured workspace root and target path, require the target to be a direct child named for the chat ID, and use `shutil.rmtree` only after containment validation. Cleanup is idempotent; a missing directory is success. Database deletion proceeds only after safe workspace cleanup succeeds, so failures remain visible and retryable.

This deliberately improves AIDev's `rm -rf` subprocess and its delete/turn race while preserving the confirmed permanent-deletion behavior.

Alternative considered: copy the source `rm -rf` call. Shell-independent validated deletion is safer and easier to test.

### Build a native, responsive Develop interface

Add Develop to the authenticated sidebar and create a protected `/develop` route. Adapt AIDev's `DevelopWorkspace`, history panel, chat panel, Markdown display, elapsed timer, pinned scrolling, incremental older-message loading, activity expansion, stream reattachment, optimistic user messages, and bounded five-chat client cache.

Use an unframed three-column desktop layout: chat history, primary conversation, and a reserved context panel. Collapse to a single primary flow on narrow screens with explicit controls for history and context. Use existing shadcn controls and Lucide icons. The repository prompt exposes one functional `Set up repository` action; it does not copy AIDev's disabled Yes/No controls. Chat deletion uses a permanent-deletion confirmation dialog. Presence options are `Stop when I leave` and `Continue in background`.

Markdown rendering uses a maintained React Markdown library with raw HTML disabled. Agent activity remains visually distinct from persisted conversation text and can be expanded without shifting the overall layout.

Alternative considered: copy the Bootstrap markup. It conflicts with the target design system and would create a second component language.

### Keep proposal decisions explicit and local

`Make it happen` summarizes the canonical stored conversation and requests `/openspec propose`. The resulting message is stored with proposal kind and no decision. Approve atomically marks it approved and starts one weighted apply turn; Reject marks it rejected and starts nothing. Repeated or conflicting decisions are rejected server-side even if the UI action is disabled.

Apply runs only inside the Development Workspace. The service does not push, publish, export, or create pull requests.

Alternative considered: trust client-only proposal state. Direct API calls could apply rejected or already-decided proposals.

### Scrub secrets at every process-output boundary

Repository token, configured repository value, OpenAI key, and credential-bearing URLs are scrubbed before output is logged, raised, streamed, or persisted. Repository credentials are passed through the process environment and Git credential helper, never embedded in command arguments or Git configuration. API payloads expose no secret-bearing configuration.

The repository URL is treated as sensitive to preserve source behavior, even when it contains no credential.

Alternative considered: scrub only logs. Agent stderr and tool output are also user-visible and persisted, so every boundary must share the same scrubber.

## Risks / Trade-offs

- [Single-process turn state reduces backend request parallelism and availability] -> Run one worker for initial correctness, document the constraint, and defer distributed coordination to a separate design.
- [Local Development Workspaces consume unbounded disk over time] -> Delete them with chats, expose configurable storage location, and record disk quotas/retention as future operational work.
- [Daemon threads are lost on backend restart] -> Persist completed messages, show interrupted active turns as no longer running after restart, and do not claim restart-resumable execution.
- [External CLI event formats can drift] -> Keep parsing isolated, ignore unknown events, validate session IDs, and cover representative fixtures from the reference implementation.
- [Repository setup can partially complete] -> Recreate from a clean chat directory on retry and surface scrubbed setup errors.
- [SSE connections can be buffered or timed out by proxies] -> Emit heartbeats, disable buffering, and document required proxy timeout behavior.
- [A malicious agent can modify anything reachable from its process] -> Pin its working directory and `--dir`, pass only required environment, and treat stronger sandboxing as future work; local directory isolation is not an OS security boundary.
- [Acceptance tests could accidentally call external services] -> Require the deterministic fake command runner in the acceptance environment and fail startup when real-agent credentials are unexpectedly selected there.

## Migration Plan

1. Add Development Chat and Development Message models and an Alembic migration.
2. Add configuration, safe workspace lifecycle, command runner, agent service, and turn manager with backend tests derived from AIDev behavior.
3. Add authenticated JSON and SSE routes, generate the OpenAPI client, and verify ownership and state transitions.
4. Add the native Develop route, navigation, panels, stream adapter, and interaction coverage.
5. Add deterministic acceptance support and implement each pending Develop scenario.
6. Install required runtime CLIs in the backend image, mount persistent workspace storage, configure environment values, and switch the initial backend deployment to one worker.
7. Run backend, frontend, and full effective acceptance suites before deployment.

Rollback disables the Develop navigation and router, stops running agent processes, and restores the prior worker command. The additive tables and workspace volume may remain for a later cleanup; they must not be destructively removed during rollback.

## Open Questions

None. Repository selection, access, runtime topology, provider, presence labels, deletion semantics, execution boundary, resource controls, and reference-code reuse were settled during design discovery.