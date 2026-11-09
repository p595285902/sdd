## Why

Context rejects ordinary documented Compose workflows: the observed demo documents initialization with `docker compose run` followed by `docker compose watch`, but detection accepts only a narrowly shaped `up` command and the custom runner rejects normal Compose configuration. Users need an explicitly launched, end-to-end application preview whose actual startup commands and output remain visible in their Development Chat.

## What Changes

- Resolve a documented Compose startup sequence from the selected checkout's root README and linked checkout-local documentation, including setup commands, working directories, environment files, and the application's entry point. Do not invent commands or rewrite the project's Compose files.
- Execute native Docker Compose inside a resource-bounded containerized sandbox owned by one Development Chat, with a dedicated Docker daemon and filesystem. Support ordinary Compose configuration, automatic override merging, documented initialization, and long-running `watch` without granting access to the platform's Docker socket or credentials.
- Allow documented project-local `.env`/environment files; isolate them from platform configuration and redact known secret values before persisting or streaming output.
- **BREAKING:** replace automatic startup on Context opening or Agent Turn completion with a Launch button beside Expand. Clicking Launch executes immediately without a separate approval dialog; preserve existing Reload/Restart behavior without implicit launches.
- Persist ordered commands, stdout/stderr, and run status as chat-visible execution records, independent of Agent Turns and reconnectable after refresh.
- Expose only the main application and its required application traffic through the owner-authenticated preview gateway. Keep database and auxiliary tool endpoints private even when the documented workflow starts them.
- Preserve the existing side-by-side Chat/Context layout, visible-Context activity reporting, five-minute idle cleanup, owner isolation, and per-chat restart/deletion cleanup. Container-level isolation is not a VM-grade hostile-code guarantee.

## Capabilities

### New Capabilities

- `develop-preview-execution`: Explicit, owner-scoped execution attempts with durable ordered command/output/status records displayed in chat.

### Modified Capabilities

- `develop-preview-compose`: Native documented multi-step Compose execution and ordinary Compose semantics inside a per-chat sandbox instead of a bespoke service subset.
- `develop-preview-instructions`: Checkout-local linked documentation and project configuration, with actionable errors for incomplete or conflicting instructions rather than blanket rejection of Compose.
- `develop-preview-startup`: Explicit launch only, readiness independent of a long-running startup command's exit, and no startup triggered by Context or completed turns.
- `develop-preview-runtime`: A dedicated Docker daemon/filesystem per chat, bounded sandbox resources, and project-local secrets without platform control or credential access.
- `develop-interface`: Launch beside Expand, persistent live execution output in the conversation, and application-only Context presentation without changing the layout.
- `develop-preview-routing`: Register only application-facing routes, not every published sandbox port or auxiliary web service.

## Impact

- Backend preview instruction resolution, lifecycle APIs, controller/runtime images, sandbox provisioning, workspace synchronization, readiness, and private application routing.
- Durable execution/event storage, owner-scoped history and streaming APIs, restart reconciliation, and frontend chat rendering; execution must not manufacture assistant replies or Agent Turns.
- Context header/preview startup handling and existing automatic triggers in frontend/backend paths.
- Docker deployment prerequisites and a pinned Docker CLI/Compose/daemon toolchain for per-chat containerized runtimes; no external VM service is required by this change.
- Acceptance fixtures and scenarios currently assuming auto-start, Compose rejection, restricted service models, or host-daemon application containers must be updated to the effective new requirements. Add deterministic demo-like coverage proving initialization, login, and item creation.
- Existing `expand-develop-preview-context` remains separate: this change preserves its layout and activity behavior. Supersede conflicting startup and unsupported-Compose requirements through deltas, not by editing main specs in this task.
