## 1. Runtime feasibility and implementation boundaries

The JavaScript acceptance project already exists; no first-time scaffolding is needed. This is an unchecked implementation checklist, not authorization to implement or commit during proposal creation. Release the specs zone through a separately authorized commit or stash before code edits. Implement only against this active change. Run the effective acceptance suite after every code change; do not declare code work complete while any scenario fails. Commit only when authorized, with specs and code in separate commits.

Each step task below means: bind the quoted pending step through an intent-level page object, observe the relevant failure, implement its product behavior, and verify it. Reuse shared step patterns/page methods without duplicate definitions. Do not satisfy a step with fixture-only assertions or disguise process output as assistant activity. The original planning dry-run reported 173 unique undefined step texts across 43 delta scenarios; the 2026-11-10 privilege revision adds explicit privileged-deployment coverage and updates the inherited checkout/network-attachment and denied-host-option assertions. Reuse previously defined regression steps and regenerate the effective inventory after revisions. Unchanged requirements remain in the source specs rather than being repeated in this delta.

- [ ] 1.1 Prove a pinned rootless Docker/Compose sandbox can build and run the demo-like workflow, named volumes, fixed sandbox-local ports/names and watch without a platform socket, injected platform credentials or shared-daemon fallback; permit an explicitly configured privileged outer container for trusted projects on a dedicated Docker host/VM, document the weakened host isolation and deployment prerequisites, and stop if infeasible within that policy.
- [ ] 1.2 Prove aggregate resource accounting, private image/package acquisition, selected-checkout-only synchronization and complete nested-resource cleanup on the supported Docker deployment.
- [ ] 1.3 Add deterministic native-Compose and login/item fixtures through `acceptance-tests/support/pages/preview-workload-page.js`; do not depend on the live demo container, workspace UUID, external repository branch or production credentials.

### Feasibility evidence — privileged smoke test passed; full gate pending

- Tested the available `rancher-desktop` Docker context: Linux/arm64 Engine 29.5.3, Alpine Linux v3.24, cgroup v2, overlay2, and the deployment's default seccomp profile. The documented production Linux Docker Engine server has not been tested; this result does not establish that every compliant deployment is infeasible.
- Pinned probe image: `docker:28.5.1-dind-rootless@sha256:87d03cfe51f2bf87eec6dda1922dc572da4d37a1d21c5ca8e8b22c8a1fa107cc`, containing Docker Compose v2.40.3 and running as the image's `rootless` user.
- Ran a disposable outer container with no host/socket/workspace mounts, no published ports, no added privileges, no networking, and aggregate limits of one CPU, 1 GiB memory and 256 processes. A 30-second timeout bounded daemon startup. Starting `/usr/local/bin/dockerd-entrypoint.sh dockerd --host=unix:///run/user/1000/docker.sock` exited 1 with `[rootlesskit:parent] error: failed to start the child: fork/exec /proc/self/exe: operation not permitted`.
- Docker's rootless-in-Docker documentation requires `--privileged` to disable seccomp, AppArmor and mount masks: <https://docs.docker.com/engine/security/rootless/tips/>. That recipe conflicted with the original no-privileged-host-access requirement and was not attempted during the initial gate. A later user-authorized diagnostic and policy revision are recorded below. No shared-daemon fallback was attempted.
- The original unprivileged gate could not demonstrate nested user namespaces/subordinate ID mapping, rootless networking/storage or effective outer aggregate CPU/memory/process/disk/lifetime bounds. At that point builds, named volumes, fixed sandbox-local names/ports, watch, acquisition, synchronization and nested cleanup were unverified because the private daemon could not start; later privileged smoke-test evidence and the approved policy revision are recorded below.
- Both probes used `--rm`; the exact feasibility label has no remaining containers. No application deployment was changed. Only this task note was edited; no product/test code was changed, and the acceptance gate was not run.
- Retried at the user's request on 2026-11-09 with the same pinned image and unprivileged bounds. The context, Engine version and reported security profile were unchanged; daemon startup again exited 1 with the same RootlessKit `operation not permitted` error. Verified no containers remained under the exact feasibility label after the retry.
- Follow-up diagnosis on 2026-11-09 isolated the first blocker to the outer container's seccomp policy, not globally disabled user namespaces: the VM reports `user.max_user_namespaces = 23826`, and its unprivileged `lima` user (no effective capabilities, `Seccomp: 0`) successfully runs `unshare -Ur id`. The image's rootless user has subordinate UID/GID mappings, but `unshare -Ur true` fails with `Operation not permitted` under `Seccomp: 2`.
- Read-only inspection of `/etc/rancher-desktop/seccomp.json` found default `SCMP_ACT_ERRNO`/errno 1, `unshare` allowed only with `CAP_SYS_ADMIN`, and namespace-creating `clone` flags excluded from the ordinary allow rule. The sandbox does not receive `CAP_SYS_ADMIN`. No sysctls, seccomp policies, capabilities or deployment settings were changed. The diagnostic container was removed.
- Before the privileged diagnostic was authorized, the proposed next experiment was a separately approved container-specific seccomp exception. The subsequent diagnostic and policy revision supersede that proposal. Do not disable seccomp globally or infer that removing one namespace blocker proves the full feasibility gate.
- At the user's explicit request on 2026-11-09, ran one disposable `--privileged` diagnostic, not a product/deployment change. The same pinned rootless image started its private Engine 28.5.1 with overlay2 and Compose v2.40.3. The outer sandbox retained one CPU, 1 GiB memory and 512-process limits, `--network none`, no host/socket mounts and no published platform ports; only image-declared anonymous volumes were attached.
- The privileged smoke test passed an offline native Compose image build using cached BusyBox image `sha256:e0e8b3cbfed68a90084781e2962f9c0deead51c5a3f11a488eef0283a4284bc2`, one-off initialization, a named volume, a fixed nested container name, detached startup, and HTTP through sandbox-local published port 18080. `compose down --volumes --rmi local` left no private containers or volumes. Outer container `sdd-privileged-probe-b3ca4741a4c1` and both anonymous volumes were removed and independently verified absent. The full demo, watch, two-chat isolation and effective resource enforcement were not tested.
- The smoke test did not satisfy task 1.1's original no-privileged-host-access requirement. At the time only task notes changed; no product/test code or deployment configuration changed, and the acceptance gate was not run.
- On 2026-11-10 the user approved spec-only revisions permitting an explicitly configured privileged outer sandbox for now, restricted to trusted projects on a dedicated Docker host/VM. The private daemon remains rootless; no platform socket, host bind mount, platform credential or other checkout is injected, and resource limits plus application-only forwarding remain required. Privileged mode is not protection against hostile projects or secure multi-tenancy.
- Task 1.1 remains unchecked until the full demo-like initialization/watch workflow, normal application images and required sandbox-local behavior are proven under that policy. The basic daemon/build/volume/HTTP smoke test is partial evidence only; task 1.2's effective aggregate bounds and acquisition/synchronization/cleanup checks remain pending. The old privilege prohibition alone no longer blocks the gate. This spec revision does not implement, deploy, commit, sync or archive anything.
- Spec-only verification on 2026-11-10: strict OpenSpec validation and extracted Gherkin lint passed. Effective dry-run `privileged-spec-final-20261110` freshly discovered 132 scenarios, including 50 from this change, with no duplicate assignment IDs or archived/backlog scenarios loaded. Superseded runtime/Compose rules are excluded, and responsive-layout/visibility scenarios remain loaded. All 183 unique undefined step texts exactly match the pending binding checklist; all 191 implementation tasks remain unchecked. HTML discovery reports are under `acceptance-tests/reports/privileged-spec-final-20261110-*.html`. This is not a passing real acceptance gate; the application was not run for this spec-only revision.

## 2. Step definitions — instruction discovery and project configuration

Adapt `develop_preview_instructions.py`, source-backed plan validation and the instruction APIs. Native Compose resolves configuration; documentation selects the workflow. Preserve existing non-Compose behavior where not superseded.

- [ ] 2.1 Bind `a Development Chat README links to checkout-local development documentation containing Compose initialization and startup instructions`.
- [ ] 2.2 Bind `the startup instructions are resolved for that chat`.
- [ ] 2.3 Bind `the ordered Compose commands are resolved with references to that documentation`.
- [ ] 2.4 Bind `alternative host-local frontend and backend commands are not combined into the Compose workflow`.
- [ ] 2.5 Bind `no command is executed during instruction discovery`.
- [ ] 2.6 Bind `a Development Chat README links to an external document or a symlink outside its checkout`.
- [ ] 2.7 Bind `startup instructions are resolved`.
- [ ] 2.8 Bind `the outside document is not read automatically`.
- [ ] 2.9 Bind `an incomplete workflow produces an actionable diagnostic in that chat`.
- [ ] 2.10 Bind `a documented Compose workflow requires a checkout-local environment file with database and first-user settings`.
- [ ] 2.11 Bind `the user launches that workflow`.
- [ ] 2.12 Bind `the sandbox uses the documented project configuration`.
- [ ] 2.13 Bind `no platform environment values or Docker credentials are inherited`.
- [ ] 2.14 Bind `known project secret values are masked before output is streamed or persisted`.
- [ ] 2.15 Bind `a Development Chat checkout has no startup commands in its README or linked checkout-local docs`.
- [ ] 2.16 Bind `the user launches the preview`.
- [ ] 2.17 Bind `the user is asked in chat for a command or a checkout-local pointer`.
- [ ] 2.18 Bind `those instructions are saved only for that chat's preview`.
- [ ] 2.19 Bind `the project remains stopped until the user launches it again`.
- [ ] 2.20 Bind `a Development Chat README documents Compose initialization followed by Compose watch`.
- [ ] 2.21 Bind `the native Compose workflow is executed in that chat's sandbox`.
- [ ] 2.22 Bind `the user is not asked to provide non-Compose commands`.
- [ ] 2.23 Bind `a Development Chat's documentation contains conflicting full-stack Docker startup instructions with no documented selection`.
- [ ] 2.24 Bind `the conflict and its source documents are identified in that chat`.
- [ ] 2.25 Bind `no startup workflow is guessed or executed`.

## 3. Step definitions — private daemon, lifetime and reconciliation

Integrate `preview_controller.py`, `develop_preview_runtime.py`, `preview_workspace_sync.py`, runtime images and `compose.yml`. The trusted controller may provision outer resources; project code must never receive its management connection. Preserve the existing visible-Context heartbeat contract.

- [ ] 3.1 Bind `two Development Chats document the same fixed container names and published application ports`.
- [ ] 3.2 Bind `both native Compose workflows are explicitly launched`.
- [ ] 3.3 Bind `both applications can run without name or port collisions`.
- [ ] 3.4 Bind `neither project's published ports are directly exposed on the platform host`.
- [ ] 3.5 Bind `the platform process has Docker connection settings and private environment credentials`.
- [ ] 3.6 Bind `a Development Chat's native Compose command executes`.
- [ ] 3.7 Bind `Docker connection settings select only that chat's private daemon`.
- [ ] 3.8 Bind `platform Docker configuration and credentials are absent from its execution environment`.
- [ ] 3.9 Bind `the deployment cannot provision a private Docker sandbox within its configured privilege policy`.
- [ ] 3.10 Bind `the user launches a preview`.
- [ ] 3.11 Bind `launch fails with an actionable diagnostic retained in the chat`.
- [ ] 3.12 Bind `execution does not fall back to the platform's shared Docker daemon`.
- [ ] 3.13 Bind `a Development Chat has a running Compose preview and persisted launch output`.
- [ ] 3.14 Bind `its sandbox and command sessions are stopped and removed`.
- [ ] 3.15 Bind `its chat retains the redacted commands, output and stopped status`.
- [ ] 3.16 Bind `a Development Chat has a running preview with no visible Context activity`.
- [ ] 3.17 Bind `its watch command continues emitting output for five minutes`.
- [ ] 3.18 Bind `the output does not keep the preview workload alive`.
- [ ] 3.19 Bind `the chat retains the final stopped status`.
- [ ] 3.20 Bind `a persisted preview execution is active but its sandbox no longer exists after controller restart`.
- [ ] 3.21 Bind `execution status is reconciled`.
- [ ] 3.22 Bind `the chat shows a terminal interrupted status for that execution`.
- [ ] 3.23 Bind `no replacement sandbox starts without an explicit user action`.
- [ ] 3.24 Bind `a trusted deployment explicitly enables privileged outer preview sandboxes`.
- [ ] 3.25 Bind `the owner launches a documented Compose preview`.
- [ ] 3.26 Bind `only that chat's outer sandbox is provisioned in privileged mode`.
- [ ] 3.27 Bind `its private Docker daemon runs as the rootless user`.
- [ ] 3.28 Bind `no platform socket, host bind mount, platform credential or other checkout is injected`.
- [ ] 3.29 Bind `aggregate sandbox resource limits remain configured`.
- [ ] 3.30 Bind `no application ports are published on the platform host`.
- [ ] 3.31 Bind `neither workload is mounted with the other chat's checkout`.

## 4. Step definitions — durable execution and output APIs

Add execution/event models and an additive migration under `backend/app/`, plus owner-scoped launch/history/stream APIs in the develop routes. Keep these records separate from `DevelopmentMessage` roles and Agent Turns. Implement transaction-safe single-active ownership, cursor replay, bounded retention and pre-persistence redaction.

- [ ] 4.1 Bind `an authenticated user owns a ready Development Chat with documented Compose startup`.
- [ ] 4.2 Bind `the user launches its preview`.
- [ ] 4.3 Bind `a preview execution attempt is recorded for that chat`.
- [ ] 4.4 Bind `no assistant message or Agent Turn is created merely to run the commands`.
- [ ] 4.5 Bind `command execution begins without a second approval request`.
- [ ] 4.6 Bind `a Development Chat has no active preview execution`.
- [ ] 4.7 Bind `two Launch requests for that chat arrive concurrently`.
- [ ] 4.8 Bind `exactly one execution owns the new sandbox`.
- [ ] 4.9 Bind `initialization executes once`.
- [ ] 4.10 Bind `both requests identify the same active execution`.
- [ ] 4.11 Bind `a Development Chat has persisted command output owned by another user`.
- [ ] 4.12 Bind `the current user requests that execution's launch controls, history or stream`.
- [ ] 4.13 Bind `access is denied`.
- [ ] 4.14 Bind `no command or output from the other chat is disclosed`.
- [ ] 4.15 Bind `a Development Chat has an active initialization command`.
- [ ] 4.16 Bind `the command emits output while still running`.
- [ ] 4.17 Bind `the chat receives its command-start and output events before command completion`.
- [ ] 4.18 Bind `those events are already durable when displayed`.
- [ ] 4.19 Bind `a browser disconnected after receiving part of a preview execution's output`.
- [ ] 4.20 Bind `it reconnects with the last received event cursor`.
- [ ] 4.21 Bind `the remaining persisted events are replayed in order`.
- [ ] 4.22 Bind `new live events continue without duplicate display or another command execution`.
- [ ] 4.23 Bind `a preview execution emits output beyond its configured retention limit`.
- [ ] 4.24 Bind `the retained output is displayed or replayed`.
- [ ] 4.25 Bind `a truncation marker identifies omitted output`.
- [ ] 4.26 Bind `command exit statuses and the execution's final status remain available`.
- [ ] 4.27 Bind `a documented project environment file supplies a known secret to a preview execution`.
- [ ] 4.28 Bind `a command prints that value across multiple stdout or stderr chunks`.
- [ ] 4.29 Bind `the secret is masked before those events are stored or delivered`.
- [ ] 4.30 Bind `replay and operational logs do not reveal the original value`.
- [ ] 4.31 Bind `a Development Chat's documentation does not identify a complete startup workflow`.
- [ ] 4.32 Bind `the owner clicks Launch`.
- [ ] 4.33 Bind `a failed execution record explains the missing instructions in that chat`.
- [ ] 4.34 Bind `no undocumented command or sandbox application service starts`.
- [ ] 4.35 Bind `a preview command prints markup or terminal control sequences`.
- [ ] 4.36 Bind `its output is displayed in the chat`.
- [ ] 4.37 Bind `the output is rendered as safe operation text`.
- [ ] 4.38 Bind `it cannot execute scripts or become an instruction for an Agent Turn`.

## 5. Step definitions — native Compose sequencing and end-to-end application

Replace the restricted `preview_compose.py` execution path with source-backed native Compose planning/preflight and supervised commands. Keep Compose files unchanged. Integrate controller command events with durable storage before exposing live output. The demo-like fixture must use initialization plus watch and prove login/item persistence, not merely an HTTP response.

- [ ] 5.1 Bind `a Development Chat README documents a one-off Compose database initialization command followed by a Compose watch command`.
- [ ] 5.2 Bind `the user launches the documented workflow`.
- [ ] 5.3 Bind `the initialization command completes successfully before the watch command starts`.
- [ ] 5.4 Bind `application readiness can be reported while the watch command remains running`.
- [ ] 5.5 Bind `both commands and their output are visible in that chat`.
- [ ] 5.6 Bind `a documented Compose workflow uses default override files, a project environment file, named volumes and a health-checked database dependency`.
- [ ] 5.7 Bind `the user launches the workflow without explicit service names`.
- [ ] 5.8 Bind `native Compose applies those files and dependency conditions inside the owning chat's sandbox`.
- [ ] 5.9 Bind `sandbox-local published ports and fixed container names do not collide with another chat or the platform`.
- [ ] 5.10 Bind `the checkout's Compose files remain unchanged`.
- [ ] 5.11 Bind `a documented Compose workflow has initialization followed by application startup`.
- [ ] 5.12 Bind `the initialization command exits with a nonzero status`.
- [ ] 5.13 Bind `the application startup command is not executed`.
- [ ] 5.14 Bind `the failed command and exit status remain visible in that chat`.
- [ ] 5.15 Bind `partial runtime resources are cleaned up only for that chat`.
- [ ] 5.16 Bind `a Development Chat has a documented Compose application with a frontend, API, database and first-user initialization`.
- [ ] 5.17 Bind `the application becomes usable inside Context`.
- [ ] 5.18 Bind `the user logs in with the initialized preview account and creates an item`.
- [ ] 5.19 Bind `the item is saved through the application's API and database`.
- [ ] 5.20 Bind `a Development Chat has a running native Compose sandbox with configured resource limits`.
- [ ] 5.21 Bind `its project creates additional services or build processes`.
- [ ] 5.22 Bind `those processes remain within the owning sandbox's aggregate resource limits`.
- [ ] 5.23 Bind `no platform secrets, host bind mounts or control sockets are injected into the sandbox`.
- [ ] 5.24 Bind `neither service is attached to the platform or another chat's private network`.
- [ ] 5.25 Bind `requested host networking and Docker socket mounts are not provisioned`.

## 6. Step definitions — explicit startup and readiness

Remove the frontend auto-start effect and backend post-turn `_start_preview` calls in `backend/app/api/routes/develop.py`, preserving explicit launch/restart APIs and existing hot reload. Context/status GETs must remain read-only. Distinguish an active command session from a ready application.

- [ ] 6.1 Bind `the user opens or expands Context before any file-changing Agent Turn`.
- [ ] 6.2 Bind `that chat's preview remains stopped`.
- [ ] 6.3 Bind `no startup command is executed`.
- [ ] 6.4 Bind `an authenticated user has selected a Development Chat with a ready checkout and documented Compose workflow`.
- [ ] 6.5 Bind `the user clicks Launch beside Expand`.
- [ ] 6.6 Bind `startup begins only for that chat without another approval dialog`.
- [ ] 6.7 Bind `startup commands and output appear in that chat while execution is in progress`.
- [ ] 6.8 Bind `a Development Chat already has a launching or running preview`.
- [ ] 6.9 Bind `another Launch request arrives for that chat`.
- [ ] 6.10 Bind `no duplicate command sequence or sandbox is created`.
- [ ] 6.11 Bind `the existing execution status is returned`.
- [ ] 6.12 Bind `a Development Chat's preview has expired after inactivity`.
- [ ] 6.13 Bind `the user reloads the chat and opens Context`.
- [ ] 6.14 Bind `the previous launch output remains available`.
- [ ] 6.15 Bind `the preview remains stopped until another explicit Launch or Restart action`.
- [ ] 6.16 Bind `the selected chat's documented Compose watch command is running`.
- [ ] 6.17 Bind `the main application begins responding on its resolved entry point`.
- [ ] 6.18 Bind `the preview becomes ready without waiting for the watch command to exit`.
- [ ] 6.19 Bind `Context displays the application rather than a supporting tool`.
- [ ] 6.20 Bind `a Development Chat's database administration tool responds while its application is still starting`.
- [ ] 6.21 Bind `readiness is checked`.
- [ ] 6.22 Bind `the preview is not marked ready for that tool`.
- [ ] 6.23 Bind `startup status continues to describe the application's progress`.

## 7. Step definitions — private application-only forwarding

Adapt the existing preview browser/service gateway and controller forwarding. Register only main-application traffic, not every native Compose port. Preserve owner checks, session stripping, redirects, assets, forms, WebSockets and API-only Swagger behavior.

- [ ] 7.1 Bind `a Development Chat's native Compose workflow publishes application, mail tool and database administration ports inside its sandbox`.
- [ ] 7.2 Bind `the owner opens the application's registered preview address`.
- [ ] 7.3 Bind `the application and its required API requests work through the private gateway`.
- [ ] 7.4 Bind `the supporting-tool ports are not registered or listed in Context`.
- [ ] 7.5 Bind `a Development Chat has a ready application and a private mail tool in its sandbox`.
- [ ] 7.6 Bind `the owner requests the mail tool's localhost port through the preview gateway`.
- [ ] 7.7 Bind `the request is rejected without contacting the mail tool`.
- [ ] 7.8 Bind `the application's registered route remains available`.
- [ ] 7.9 Bind `two Development Chats run applications using the same sandbox-local published port`.
- [ ] 7.10 Bind `their owners open their respective registered preview addresses`.
- [ ] 7.11 Bind `each address reaches only its owning chat's application`.
- [ ] 7.12 Bind `neither sandbox port is exposed directly on the platform host`.

## 8. Step definitions — Launch control and persistent conversation rendering

Update `DevelopWorkspace.tsx`, `DevelopPreview.tsx`, preview API clients and an independent operation-event state path. Merge execution records into conversation history without changing Development Message roles or the Agent Turn reducer. Retain the current desktop/mobile layout and visibility heartbeat behavior.

- [ ] 8.1 Bind `an authenticated user has selected a Development Chat with a ready checkout and stopped preview`.
- [ ] 8.2 Bind `Launch is available beside Expand`.
- [ ] 8.3 Bind `opening Context does not execute startup commands`.
- [ ] 8.4 Bind `the conversation remains accessible alongside Context on desktop`.
- [ ] 8.5 Bind `the selected chat has a ready checkout and resolvable Docker startup instructions`.
- [ ] 8.6 Bind `the user clicks Launch`.
- [ ] 8.7 Bind `that chat's startup begins without an approval dialog`.
- [ ] 8.8 Bind `Launch indicates progress without allowing another concurrent launch`.
- [ ] 8.9 Bind `startup output appears in the conversation while Context remains available`.
- [ ] 8.10 Bind `the user opens Context through its mobile control`.
- [ ] 8.11 Bind `Launch and Expand remain accessible without horizontal page overflow`.
- [ ] 8.12 Bind `launching the application does not remove access to the conversation`.
- [ ] 8.13 Bind `a Development Chat's documented Compose workflow starts an application, a mail tool and a database administration tool`.
- [ ] 8.14 Bind `the application becomes ready`.
- [ ] 8.15 Bind `Context embeds the application`.
- [ ] 8.16 Bind `Context does not list or link the supporting tools`.
- [ ] 8.17 Bind `a Development Chat has a launching Compose preview`.
- [ ] 8.18 Bind `a command emits stdout and stderr before the application becomes ready`.
- [ ] 8.19 Bind `its command and both output streams appear incrementally in that chat's execution entry`.
- [ ] 8.20 Bind `the output is not presented as an assistant reply or Agent Turn`.
- [ ] 8.21 Bind `Context and the conversation remain usable side by side on desktop`.
- [ ] 8.22 Bind `a Development Chat has an active preview execution with persisted output`.
- [ ] 8.23 Bind `the user refreshes and reopens that chat`.
- [ ] 8.24 Bind `the same execution entry and output are restored`.
- [ ] 8.25 Bind `new output attaches to that entry without duplicated events or another launch`.
- [ ] 8.26 Bind `a Development Chat's initialization command failed and its sandbox was removed`.
- [ ] 8.27 Bind `the user revisits the chat`.
- [ ] 8.28 Bind `the failed command, redacted diagnostic and exit status remain visible`.
- [ ] 8.29 Bind `the interface does not launch a replacement preview automatically`.

## 9. Completion

- [ ] 9.1 Run the complete effective acceptance gate with zero failures, pending or undefined steps and an HTML report; preserve source-only regressions where requirements are unchanged.
- [ ] 9.2 Verify composition loads no archived, duplicated or superseded auto-start/unsupported-Compose scenarios, and retains the separate responsive-layout/visibility change's scenarios.
- [ ] 9.3 Run focused backend/frontend tests for durable events, concurrent launch, chunk-spanning redaction, stream replay, safe output, application routing, sandbox reconciliation and Launch placement.
- [ ] 9.4 Verify the demo-like initialization/watch workflow through browser login and item creation, plus two-chat port/name isolation and five-minute cleanup retaining output.
- [ ] 9.5 Record deployment privilege policy, dedicated-host/trusted-project prerequisites, privileged-mode risks, verified output/resource bounds and rollback behavior; obtain any separately required authorization before committing code or syncing/archiving specs.
