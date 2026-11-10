## Context

The observed demo's README documents `docker compose run --rm backend bash scripts/prestart.sh` followed by `docker compose watch`. A read-only invocation of the deployed `documented_compose()` returned `None`. The deployed detector and Context route matched repository hashes. This establishes an instruction-detection failure, not a failed live launch; the direct owner/DB diagnostic was not available and was not needed for this conclusion.

Relevant inspected integration points:

- `backend/app/services/preview_compose.py:25-66` reads only root README lines and recognizes `up` with explicitly named services. Its graph validator (`:79-164`) rejects ordinary environment, volume, health-check, dependency-condition, image and override semantics.
- `backend/app/api/routes/develop.py:1086-1126` uses that detector and validator for Context support before controller status. Existing `preview/launch` (`:1159-1223`) also contains obsolete unsupported-Compose guidance and creates assistant messages for instruction errors.
- `compose.yml:116-130` provisions a trusted preview controller with the platform Docker socket. This is a separate controller container, not a private Docker engine for project code. `backend/preview.Dockerfile` currently supplies language tools, not native Docker/Compose or an isolated daemon.
- `frontend/src/features/develop/DevelopWorkspace.tsx:474-509` owns Context Expand/Close controls. `DevelopPreview.tsx:190-257` automatically starts a stopped supported preview; polling, browser authorization, heartbeat and explicit Restart are separate paths to preserve.
- `backend/app/models.py:233-298` represents user/assistant messages, not independent operations. `frontend/src/features/develop/state.ts:99-134` is an Agent Turn reducer, not a generic process-output stream. Existing chat rendering/history must merge preview execution records without disguising them as assistant replies.
- Existing acceptance fixtures in `acceptance-tests/support/pages/preview-workload-page.js` exercise the restricted runner and non-Compose fallback. They are useful integration seams but do not establish native Compose compatibility.

The current source specs conflict with the confirmed design: `develop-preview-startup` requires automatic Context/turn-triggered startup; `develop-preview-instructions` still contains blanket unsupported-Compose guidance; `develop-preview-compose` disallows all project environment interpolation and published ports. The deltas replace these behaviors explicitly. The active `expand-develop-preview-context` layout/visibility delta remains untouched.

The initial unprivileged rootless probe failed on Rancher Desktop because its outer-container seccomp policy blocks namespace creation. A later user-authorized privileged outer-container smoke test started rootless Engine 28.5.1 and Compose v2.40.3 and passed an offline build, initialization, named-volume storage and sandbox-local HTTP; cleanup removed the outer container and its volumes. This did not test the full demo/watch workflow, two-chat isolation or effective aggregate bounds. On 2026-11-10 the user approved permitting a privileged outer sandbox for now, while retaining the private rootless daemon and other provisioning constraints. The runtime delta explicitly removes the inherited no-privileged-host-access requirement and replaces it with a chat-scoped provisioning contract rather than leaving contradictory source behavior active.

## Goals / Non-Goals

**Goals:**

- Run documented, ordinary Compose applications end to end using their initialization and startup commands, including `run` then `watch`.
- Require an explicit Launch or Restart action, with no second approval and no launch on Context opening, turn completion, refresh or heartbeat.
- Give each Development Chat a containerized, resource-bounded private rootless Docker runtime and filesystem without injecting the platform's daemon socket, credentials or other chats' checkouts; permit an explicitly configured privileged outer sandbox for trusted workloads on a dedicated Docker host or VM.
- Persist redacted live commands/output/status in the conversation independently of Agent Turns.
- Embed only the application, keeping supporting tools and data ports private.
- Preserve side-by-side Chat/Context, existing explicit Reload/Restart and visible-Context/five-minute-idle behavior.

**Non-Goals:**

- VM/microVM provisioning, a claim of VM-grade containment, or treating a privileged outer sandbox as protection against malicious/compromised projects or secure multi-tenancy.
- Executing README snippets on the backend/platform host, exposing the platform socket to project code, or silently falling back to the shared daemon.
- Arbitrary undocumented workflows, generated replacement Compose files, automatic repairs, auxiliary-tool navigation, or changing the workspace layout.
- Removing supported non-Compose APIs or adding non-Compose embedding to Context.
- Syncing/archiving specs, implementing code, or changing the live demo during this planning task.

## Decisions

### 1. A private native Docker runtime with a permitted privileged outer sandbox

The trusted controller continues to provision outer sandbox containers through its management connection. Each sandbox owns a private rootless Docker daemon, its data directory, a command supervisor, a private workspace and its nested Compose resources. The daemon is a process inside the outer sandbox, not an additional daemon container. Project Docker CLI/Compose commands receive only that private daemon endpoint. Do not mount the platform socket, Docker client credentials, platform environment, platform host paths or a volume containing all Development Chats into the sandbox.

Use a pinned native Docker CLI/Compose/daemon toolchain. Keep the daemon rootless and prefer an unprivileged outer sandbox where supported. For now, deployment configuration may explicitly enable `--privileged` for the outer sandbox only, on a dedicated Docker host or VM running trusted projects. Project documentation/configuration cannot enable this mode or request privileged inner services. This deployment policy adds no second user approval dialog to Launch. Privileged mode relaxes outer capability, seccomp, device and mount protections; the rootless daemon does not restore the outer boundary. A malicious or compromised project could affect the Docker host, its accessible secrets/files or other workloads. Do not promise hostile-code containment or secure isolation between mutually untrusted chats in this mode.

Before product implementation proceeds, prove nested builds, normal application images, volume writes, sandbox-local port publication and Compose watch on the supported Docker deployment under the explicitly configured privilege policy. The privileged smoke test is partial evidence, not completion of this gate. If the deployment cannot provide the private runtime within its configured policy, fail closed with a deployment diagnostic; never silently escalate an unprivileged deployment or fall back to the shared daemon.

Bound aggregate CPU, memory, process count, disk consumption and startup/idle time around the outer sandbox, including nested builds and containers. Verify effective bounds in the selected privilege mode rather than assuming rootless inner cgroup support. Application images may use the users they require, such as a database image's initialization user; do not impose a Python/Node-only inner image/user list. The accepted outer-container privilege exception does not authorize project-requested host paths/control sockets, privileged inner containers, sources outside the selected checkout or direct platform port publication. These are provisioning/preflight constraints for trusted workloads, not a guarantee against escape from a privileged container.

Alternatives rejected: adding individual keys to the bespoke graph parser would continue to diverge from Compose; a unique project name on the shared platform daemon would not separate fixed container names, ports or daemon control; VM-backed execution has stronger isolation but was explicitly not selected. A dedicated existing Docker host/VM is a deployment prerequisite for privileged mode, not a new VM-provisioning architecture.

### 2. A source-backed startup plan, resolved without starting anything

Introduce a structured plan containing documentation references, working directory, ordered setup/start commands, selected Compose files/profiles/services when documented, project environment-file paths, and the main application entry point. Follow only checkout-local documentation links from root README; normalize fragments, deduplicate identical instructions and bound traversal. Initial configurable limits: four link levels, sixteen documents and one MiB total text. Reject symlink/path escape, cycles beyond the traversal budget and external-document fetches.

Prefer a clearly documented full-stack Docker workflow over an explicitly alternative host-local development workflow. Do not concatenate every Docker example in a README or confuse maintenance/test/stop examples with startup. If multiple full-stack workflows conflict without a documented choice, record a needs-instructions failure and execute nothing. Every executable plan step must cite the checkout-local instruction from which it was resolved. Existing instruction-resolution utilities can be adapted, but any inferred structure must be validated against those sources; project secret values are not inputs to a remote instruction resolver.

Resolve `.env`, `env_file`, override merging, build configuration, default service selection and dependency conditions with native Compose in the private sandbox, not a second hand-written YAML implementation. A non-starting configuration/preflight phase may run only after an explicit launch. Do not edit the checkout to make it fit.

### 3. Preserve command semantics and supervise long-running startup

Run commands in the documented directory and order inside the sandbox with a minimal environment plus permitted project configuration. One-off setup must exit successfully before its dependent start step. Preserve native default override loading and omission of service names. Record actual argv/directory and a redacted display command before execution. Supported compound sequencing must retain documented failure semantics; never evaluate shell text in the backend process.

For the motivating workflow, execute initialization and then supervise `docker compose watch` as a continuing session. A long-running process is not itself proof of readiness, and becoming ready does not mean that process exited. For detached startup, continue tracking the sandbox/application after the CLI command exits. Report command failures, unexpected required-session exits and readiness timeouts distinctly.

Use the selected checkout as the source for one-way workspace synchronization into the sandbox. Include documented project environment files intentionally, while excluding platform files, other checkouts and unrelated credentials. Subsequent source changes reach the sandbox so native watch/reload can act. Keep nested build outputs/dependencies/volumes private; do not sync them back into the authoritative checkout or implicitly launch a stopped sandbox after a turn.

### 4. Private application routing, not all-port publication

Native `ports` bindings terminate inside the sandbox's network namespace. The outer platform publishes no corresponding application ports. A narrowly scoped forwarding path exposes only the selected main application through the existing owner-authenticated gateway; it is not a general reverse route from a sandbox into the backend/control network.

Resolve service target ports from effective Compose configuration and use documentation to identify the application. Do not treat a responding Mailpit/Adminer port as the application or register every published port. Preserve only required application API/assets/forms/WebSocket traffic; an API-only application's Swagger page remains its primary application entry point. Supporting tool and database endpoints remain unregistered even for the owner.

Readiness checks the resolved application response and honors native required-dependency ordering. Auxiliary service readiness alone is insufficient. Report Compose health/build output, but do not invent a requirement that every optional/test/tool service must be healthy before an otherwise usable application is shown. Genuine inconsistent entry-point instructions must fail diagnostically, not be silently rewritten.

### 5. Durable executions/events separate from conversation messages

Add chat-owned execution and execution-event persistence with stable IDs, timestamps, workflow/source snapshot, command metadata, sequence cursor and status. Keep the existing user/assistant Development Message meaning unchanged. The conversation merges operation entries chronologically with ordinary messages, but starting a preview does not create an Agent Turn, fake assistant reply or automatic model invocation.

A database transaction/ownership lock ensures one active runtime-owning execution per chat. Concurrent Launch requests return that execution rather than repeat initialization. An explicit Restart terminates the prior workload with a recorded reason before starting a new attempt. Execution state and application readiness are separate: an execution can remain running while its application is ready.

Persist events before streaming them through an independent owner-authenticated preview-output endpoint. Reuse transport/authentication conventions, not the Agent Turn reducer. Replay after a cursor and deduplicate by execution ID plus sequence. Store command start, stdout/stderr, exit and lifecycle events. Batch writes/backpressure are bounded; truncation/gap markers are explicit, and terminal status is always retained. The UI shows persistent expandable command/output entries next to Context without any extra approval step.

Mask known project credential/secret values before all persistence, browser streams and operational logging, including command arguments and values split across chunks. Maintain a bounded redaction buffer; update known values when an allowed project environment file changes. Render output as safe text, not Markdown/HTML instructions. Redaction is best-effort masking of known values, not protection against arbitrary deliberate encodings or disclosure by hostile code. Runtime expiration removes private `.env` copies and data but retains redacted history; chat deletion removes both.

### 6. Explicit launch with existing layout and lifetime

Lift/share preview launch state between the Context header and preview component. Place Launch beside Expand, make it pending/disabled appropriately, and leave the existing responsive layout intact. Remove frontend auto-start and backend post-turn auto-start triggers. Read-only Context/status requests, browser reattachment and heartbeats must never provision resources or execute startup commands. Keep explicit Reload and Restart.

The current visible-Context heartbeat contract remains authoritative: both Context and browser tab must be visible. Closing Context, changing chats or hiding the tab stops heartbeat; five minutes without that activity expires the workload. Output traffic or an open conversation stream does not extend its life. Expiry never restarts it automatically. Controller restart reconciles recorded active executions against actual owned sandboxes; missing sandboxes become interrupted rather than phantom-running or silently relaunched.

## Risks / Trade-offs

- Rootless nested Docker may depend on host user namespaces, storage drivers, networking and outer security policy → run the full feasibility gate with the configured privilege policy; publish prerequisites, allow the approved privileged outer mode explicitly, and fail closed rather than silently escalating or sharing the platform daemon.
- Privileged outer containers relax host protections and can allow malicious or compromised projects to affect the Docker host and other workloads → limit this temporary mode to trusted projects on a dedicated Docker host/VM; retain the rootless private daemon, resource bounds and no socket/credential/host-bind injection, while documenting that these do not restore hostile-code containment or secure multi-tenancy.
- Native image/build compatibility needs more sources than the old pinned Python/Node pair → configure explicit public image/package/build-source access; deny platform/private-network destinations and inherited platform registry credentials.
- Project `.env` can contain sensitive or external-service credentials → keep it chat-local, restrict network destinations, mask known values before storage, and never describe masking as complete exfiltration prevention.
- Persistent watch output can grow without bound or contain active markup → bounded storage/stream buffers, explicit truncation, safe text and retained terminal events.
- Browser closure, deployment restart or duplicate requests can orphan long-running sessions → durable active ownership, idempotent launch, resource labels, reconciliation and per-chat teardown.
- Arbitrary documented projects can be genuinely broken → preserve their commands/configuration and show the actual redacted failure, rather than auto-fix code or claim every Compose project is supported.

## Migration Plan

1. Add deterministic acceptance fixtures for native Compose, initialization, configuration/overrides, isolation, persistent output and manual launch. Replace superseded auto-start/blanket Compose-rejection expectations through the effective deltas.
2. Prove the rootless daemon/toolchain on the supported Docker deployment with its explicitly configured outer privilege policy, including port/name collision separation, effective aggregate resource accounting, Compose watch, restart and idle teardown. Record dedicated-host/trusted-project prerequisites and privileged-mode risks before connecting real user launches.
3. Add execution/event storage and owner-scoped APIs with additive migrations; integrate controller event delivery and reconciliation before switching UI behavior.
4. Add native workflow resolution/runtime forwarding and explicit Launch; route native sandbox operations through the same bounded cleanup contract. Remove obsolete automatic startup and unsupported-Compose guidance.
5. Run the effective acceptance suite after every implementation change, then verify the demo-like full stack through initialization, login and item creation. Keep all existing isolation, browser authentication, layout and heartbeat regressions green.
6. Rollback: stop owned native sandboxes and disable their launch path; keep execution tables/history so persisted output is not lost. Do not revert to automatic startup or pass project commands to the shared daemon as a fallback.

## Open Questions

No unresolved product choices remain from the interview or the 2026-11-10 privilege revision. Implementation must verify the pinned rootless Docker/Compose toolchain, full initialization/watch workflow, nested storage/network support, effective aggregate bounds and cross-platform prerequisites in the bounded feasibility task. An explicitly configured privileged outer sandbox is now permitted for trusted dedicated deployments; the successful smoke test does not complete those remaining checks. Failure of the full gate must be reported before substituting a different architecture or weakening other requirements.
