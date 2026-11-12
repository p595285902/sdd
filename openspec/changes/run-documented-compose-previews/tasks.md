## 1. Runtime feasibility and implementation boundaries

The JavaScript acceptance project already exists; no first-time scaffolding is needed. This is an unchecked implementation checklist, not authorization to implement or commit during proposal creation. Release the specs zone through a separately authorized commit or stash before code edits. Implement only against this active change. Run the effective acceptance suite after every code change; do not declare code work complete while any scenario fails. Commit only when authorized, with specs and code in separate commits.

Each step task below means: bind the quoted pending step through an intent-level page object, observe the relevant failure, implement its product behavior, and verify it. Reuse shared step patterns/page methods without duplicate definitions. Do not satisfy a step with fixture-only assertions or disguise process output as assistant activity. The original planning dry-run reported 173 unique undefined step texts across 43 delta scenarios; the 2026-11-10 privilege revision adds explicit privileged-deployment coverage and updates the inherited checkout/network-attachment and denied-host-option assertions. Reuse previously defined regression steps and regenerate the effective inventory after revisions. Unchanged requirements remain in the source specs rather than being repeated in this delta.

- [x] 1.1 Prove a pinned rootless Docker/Compose sandbox can build and run the demo-like workflow, named volumes, fixed sandbox-local ports/names and watch without a platform socket, injected platform credentials or shared-daemon fallback; permit an explicitly configured privileged outer container for trusted projects on a dedicated Docker host/VM, document the weakened host isolation and deployment prerequisites, and stop if infeasible within that policy.
- [x] 1.2 Prove aggregate resource accounting, private image/package acquisition, selected-checkout-only synchronization and complete nested-resource cleanup on the supported Docker deployment.
- [x] 1.3 Add deterministic native-Compose and login/item fixtures through `acceptance-tests/support/pages/preview-workload-page.js`; do not depend on the live demo container, workspace UUID, external repository branch or production credentials.

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

### Implementation feasibility evidence — 2026-11-10

- Task 1.1 passed on the available Rancher Desktop Linux/arm64 Engine 29.5.3 deployment using the pinned rootless Docker 28.5.1 / Compose v2.40.3 image above. Disposable diagnostic sources, fixture and logs are in `/tmp/sdd-native-feasibility.jreQFP/` (`probe.py`, `probe.log`, per-sandbox inspect/daemon/watch logs). These are runtime probes, not product acceptance tests or a production Linux certification.
- Two explicitly privileged outer containers each ran as `rootless` with `--network none`, a read-only root filesystem, 0.5 CPU, 1536 MiB memory/swap total, 512 processes and capped tmpfs writable paths (1024 MiB Docker data, 32 MiB home, 16 MiB runtime, 16 MiB temporary files, 1 MiB unused rootful data). Inspection showed no mounts or published platform ports. Only an explicit fixture tar stream and cached public Python/Postgres images entered the private daemons; no platform socket, host bind, credentials or other checkout was supplied.
- A deterministic frontend/API/Postgres 16 fixture passed native builds, default override/environment resolution, health-conditioned database dependencies, first-user initialization with `compose run --rm`, followed by supervised `compose watch`. Login and item creation crossed the frontend HTTP proxy, API and real Postgres database. A source-only tar update reached the website through native watch. Compose files remained byte-identical.
- Both sandboxes simultaneously used the same fixed database/API/website container names and published ports (15432/18081/18080), with distinct saved items and no collision. Nested API processes saw the outer `cpu.max=50000 100000`, `memory.max=1610612736`, `pids.max=512`; outer CPU throttling was observed. Rootless Docker reported no independent inner cgroup driver, so outer enforcement must remain authoritative.
- Cleanup inspected the exact ownership labels, removed both outer containers and verified none remained. There were no attached persistent volumes or host/network resources to orphan. This does not yet verify product idle cleanup, browser/Context integration, restricted online acquisition or every resource limit; task 1.2 and later acceptance tasks remain separate.
- Privileged-mode prerequisite/risk remains unchanged: explicit deployment policy, trusted projects and a dedicated Docker host/VM only. Privilege relaxes host protections; a rootless inner daemon, capped storage and no injected credentials do not restore hostile-code containment or secure multi-tenancy. Do not silently enable privilege or fall back to the shared daemon on unsupported deployments.
- Task 1.2's additional bounded diagnostic passed (`acquisition_probe.py`, `acquisition.log`, inspect/daemon logs and `bounded-storage-mounts.txt` in the same directory). A network-disabled rootless sandbox pulled BusyBox by digest from Docker Hub and built an image installing `six==1.17.0` from PyPI, without registry credentials. The only acquisition transport was a read-only named-volume Unix socket to an independently bounded trusted CONNECT proxy; a trusted nested forwarder made it available to the private daemon/build network. The proxy allowed explicit official Docker Hub/CDN, npm and PyPI domains, checked public DNS addresses and TLS SNI, and rejected example.com, loopback and RFC1918 destinations with 403 before connecting. No platform network or host bind was attached to project workloads.
- Effective outer cgroup CPU throttling was observed during native builds; nested application and allocation processes saw the same 0.5-CPU/1536-MiB/512-process ancestor limits. Writable daemon layers, image/build cache and named-volume data used the capped 1-GiB tmpfs rather than unbounded outer overlay storage. A 20-MiB write to the capped 16-MiB temporary mount failed with ENOSPC. The read-only root filesystem plus individually capped home/runtime/temp/data mounts bounds ordinary trusted-workload writes; this is not a malicious privileged-container containment claim. Memory-backed storage consumes the aggregate memory budget and must be sized with the application/build working set.
- Acquisition cleanup inspected exact ownership, removed the outer sandbox and trusted egress helper, removed their socket volume, and independently verified no labeled containers or volumes remained. Together with the selected fixture-only tar streams and simultaneous independent chat data in the offline probe, this completes the bounded feasibility tasks on this deployment. Product lifecycle/idle cleanup, history retention and browser integration remain unimplemented and require their own acceptance tests. Other Linux deployments must meet and verify the same prerequisites rather than inheriting certification from Rancher Desktop.
- Effective acceptance discovery was rerun with prefix `native-feasibility-discovery-20261110`: 132 scenarios assigned; superseded source requirements were excluded. This dry-run is not a passing acceptance gate. No product/test code was edited for these diagnostics.

## 2. Step definitions — instruction discovery and project configuration

Adapt `develop_preview_instructions.py`, source-backed plan validation and the instruction APIs. Native Compose resolves configuration; documentation selects the workflow. Preserve existing non-Compose behavior where not superseded.

- [x] 2.1 Bind `a Development Chat README links to checkout-local development documentation containing Compose initialization and startup instructions`.
- [x] 2.2 Bind `the startup instructions are resolved for that chat`.
- [x] 2.3 Bind `the ordered Compose commands are resolved with references to that documentation`.
- [x] 2.4 Bind `alternative host-local frontend and backend commands are not combined into the Compose workflow`.
- [x] 2.5 Bind `no command is executed during instruction discovery`.
- [x] 2.6 Bind `a Development Chat README links to an external document or a symlink outside its checkout`.
- [x] 2.7 Bind `startup instructions are resolved`.
- [x] 2.8 Bind `the outside document is not read automatically`.
- [x] 2.9 Bind `an incomplete workflow produces an actionable diagnostic in that chat`.
- [x] 2.10 Bind `a documented Compose workflow requires a checkout-local environment file with database and first-user settings`.
- [x] 2.11 Bind `the user launches that workflow`.
- [x] 2.12 Bind `the sandbox uses the documented project configuration`.
- [x] 2.13 Bind `no platform environment values or Docker credentials are inherited`.
- [x] 2.14 Bind `known project secret values are masked before output is streamed or persisted`.
- [x] 2.15 Bind `a Development Chat checkout has no startup commands in its README or linked checkout-local docs`.
- [x] 2.16 Bind `the user launches the preview`.
- [x] 2.17 Bind `the user is asked in chat for a command or a checkout-local pointer`.
- [x] 2.18 Bind `those instructions are saved only for that chat's preview`.
- [x] 2.19 Bind `the project remains stopped until the user launches it again`.
- [x] 2.20 Bind `a Development Chat README documents Compose initialization followed by Compose watch`.
- [x] 2.21 Bind `the native Compose workflow is executed in that chat's sandbox`.
- [x] 2.22 Bind `the user is not asked to provide non-Compose commands`.
- [x] 2.23 Bind `a Development Chat's documentation contains conflicting full-stack Docker startup instructions with no documented selection`.
- [x] 2.24 Bind `the conflict and its source documents are identified in that chat`.
- [x] 2.25 Bind `no startup workflow is guessed or executed`.

## 3. Step definitions — private daemon, lifetime and reconciliation

Integrate `preview_controller.py`, `develop_preview_runtime.py`, `preview_workspace_sync.py`, runtime images and `compose.yml`. The trusted controller may provision outer resources; project code must never receive its management connection. Preserve the existing visible-Context heartbeat contract.

- [x] 3.1 Bind `two Development Chats document the same fixed container names and published application ports`.
- [x] 3.2 Bind `both native Compose workflows are explicitly launched`.
- [x] 3.3 Bind `both applications can run without name or port collisions`.
- [x] 3.4 Bind `neither project's published ports are directly exposed on the platform host`.
- [x] 3.5 Bind `the platform process has Docker connection settings and private environment credentials`.
- [x] 3.6 Bind `a Development Chat's native Compose command executes`.
- [x] 3.7 Bind `Docker connection settings select only that chat's private daemon`.
- [x] 3.8 Bind `platform Docker configuration and credentials are absent from its execution environment`.
- [x] 3.9 Bind `the deployment cannot provision a private Docker sandbox within its configured privilege policy`.
- [x] 3.10 Bind `the user launches a preview`.
- [x] 3.11 Bind `launch fails with an actionable diagnostic retained in the chat`.
- [x] 3.12 Bind `execution does not fall back to the platform's shared Docker daemon`.
- [x] 3.13 Bind `a Development Chat has a running Compose preview and persisted launch output`.
- [x] 3.14 Bind `its sandbox and command sessions are stopped and removed`.
- [x] 3.15 Bind `its chat retains the redacted commands, output and stopped status`.
- [x] 3.16 Bind `a Development Chat has a running preview with no visible Context activity`.
- [x] 3.17 Bind `its watch command continues emitting output for five minutes`.
- [x] 3.18 Bind `the output does not keep the preview workload alive`.
- [x] 3.19 Bind `the chat retains the final stopped status`.
- [x] 3.20 Bind `a persisted preview execution is active but its sandbox no longer exists after controller restart`.
- [x] 3.21 Bind `execution status is reconciled`.
- [x] 3.22 Bind `the chat shows a terminal interrupted status for that execution`.
- [x] 3.23 Bind `no replacement sandbox starts without an explicit user action`.
- [x] 3.24 Bind `a trusted deployment explicitly enables privileged outer preview sandboxes`.
- [x] 3.25 Bind `the owner launches a documented Compose preview`.
- [x] 3.26 Bind `only that chat's outer sandbox is provisioned in privileged mode`.
- [x] 3.27 Bind `its private Docker daemon runs as the rootless user`.
- [x] 3.28 Bind `no platform socket, host bind mount, platform credential or other checkout is injected`.
- [x] 3.29 Bind `aggregate sandbox resource limits remain configured`.
- [x] 3.30 Bind `no application ports are published on the platform host`.
- [x] 3.31 Bind `neither workload is mounted with the other chat's checkout`.

## 4. Step definitions — durable execution and output APIs

Add execution/event models and an additive migration under `backend/app/`, plus owner-scoped launch/history/stream APIs in the develop routes. Keep these records separate from `DevelopmentMessage` roles and Agent Turns. Implement transaction-safe single-active ownership, cursor replay, bounded retention and pre-persistence redaction.

- [x] 4.1 Bind `an authenticated user owns a ready Development Chat with documented Compose startup`.
- [x] 4.2 Bind `the user launches its preview`.
- [x] 4.3 Bind `a preview execution attempt is recorded for that chat`.
- [x] 4.4 Bind `no assistant message or Agent Turn is created merely to run the commands`.
- [x] 4.5 Bind `command execution begins without a second approval request`.
- [x] 4.6 Bind `a Development Chat has no active preview execution`.
- [x] 4.7 Bind `two Launch requests for that chat arrive concurrently`.
- [x] 4.8 Bind `exactly one execution owns the new sandbox`.
- [x] 4.9 Bind `initialization executes once`.
- [x] 4.10 Bind `both requests identify the same active execution`.
- [x] 4.11 Bind `a Development Chat has persisted command output owned by another user`.
- [x] 4.12 Bind `the current user requests that execution's launch controls, history or stream`.
- [x] 4.13 Bind `access is denied`.
- [x] 4.14 Bind `no command or output from the other chat is disclosed`.
- [x] 4.15 Bind `a Development Chat has an active initialization command`.
- [x] 4.16 Bind `the command emits output while still running`.
- [x] 4.17 Bind `the chat receives its command-start and output events before command completion`.
- [x] 4.18 Bind `those events are already durable when displayed`.
- [x] 4.19 Bind `a browser disconnected after receiving part of a preview execution's output`.
- [x] 4.20 Bind `it reconnects with the last received event cursor`.
- [x] 4.21 Bind `the remaining persisted events are replayed in order`.
- [x] 4.22 Bind `new live events continue without duplicate display or another command execution`.
- [x] 4.23 Bind `a preview execution emits output beyond its configured retention limit`.
- [x] 4.24 Bind `the retained output is displayed or replayed`.
- [x] 4.25 Bind `a truncation marker identifies omitted output`.
- [x] 4.26 Bind `command exit statuses and the execution's final status remain available`.
- [x] 4.27 Bind `a documented project environment file supplies a known secret to a preview execution`.
- [x] 4.28 Bind `a command prints that value across multiple stdout or stderr chunks`.
- [x] 4.29 Bind `the secret is masked before those events are stored or delivered`.
- [x] 4.30 Bind `replay and operational logs do not reveal the original value`.
- [x] 4.31 Bind `a Development Chat's documentation does not identify a complete startup workflow`.
- [x] 4.32 Bind `the owner clicks Launch`.
- [x] 4.33 Bind `a failed execution record explains the missing instructions in that chat`.
- [x] 4.34 Bind `no undocumented command or sandbox application service starts`.
- [x] 4.35 Bind `a preview command prints markup or terminal control sequences`.
- [x] 4.36 Bind `its output is displayed in the chat`.
- [x] 4.37 Bind `the output is rendered as safe operation text`.
- [x] 4.38 Bind `it cannot execute scripts or become an instruction for an Agent Turn`.

## 5. Step definitions — native Compose sequencing and end-to-end application

Replace the restricted `preview_compose.py` execution path with source-backed native Compose planning/preflight and supervised commands. Keep Compose files unchanged. Integrate controller command events with durable storage before exposing live output. The demo-like fixture must use initialization plus watch and prove login/item persistence, not merely an HTTP response.

- [x] 5.1 Bind `a Development Chat README documents a one-off Compose database initialization command followed by a Compose watch command`.
- [x] 5.2 Bind `the user launches the documented workflow`.
- [x] 5.3 Bind `the initialization command completes successfully before the watch command starts`.
- [x] 5.4 Bind `application readiness can be reported while the watch command remains running`.
- [x] 5.5 Bind `both commands and their output are visible in that chat`.
- [x] 5.6 Bind `a documented Compose workflow uses default override files, a project environment file, named volumes and a health-checked database dependency`.
- [x] 5.7 Bind `the user launches the workflow without explicit service names`.
- [x] 5.8 Bind `native Compose applies those files and dependency conditions inside the owning chat's sandbox`.
- [x] 5.9 Bind `sandbox-local published ports and fixed container names do not collide with another chat or the platform`.
- [x] 5.10 Bind `the checkout's Compose files remain unchanged`.
- [x] 5.11 Bind `a documented Compose workflow has initialization followed by application startup`.
- [x] 5.12 Bind `the initialization command exits with a nonzero status`.
- [x] 5.13 Bind `the application startup command is not executed`.
- [x] 5.14 Bind `the failed command and exit status remain visible in that chat`.
- [x] 5.15 Bind `partial runtime resources are cleaned up only for that chat`.
- [x] 5.16 Bind `a Development Chat has a documented Compose application with a frontend, API, database and first-user initialization`.
- [x] 5.17 Bind `the application becomes usable inside Context`.
- [x] 5.18 Bind `the user logs in with the initialized preview account and creates an item`.
- [x] 5.19 Bind `the item is saved through the application's API and database`.
- [x] 5.20 Bind `a Development Chat has a running native Compose sandbox with configured resource limits`.
- [x] 5.21 Bind `its project creates additional services or build processes`.
- [x] 5.22 Bind `those processes remain within the owning sandbox's aggregate resource limits`.
- [x] 5.23 Bind `no platform secrets, host bind mounts or control sockets are injected into the sandbox`.
- [x] 5.24 Bind `neither service is attached to the platform or another chat's private network`.
- [x] 5.25 Bind `requested host networking and Docker socket mounts are not provisioned`.

## 6. Step definitions — explicit startup and readiness

Remove the frontend auto-start effect and backend post-turn `_start_preview` calls in `backend/app/api/routes/develop.py`, preserving explicit launch/restart APIs and existing hot reload. Context/status GETs must remain read-only. Distinguish an active command session from a ready application.

- [x] 6.1 Bind `the user opens or expands Context before any file-changing Agent Turn`.
- [x] 6.2 Bind `that chat's preview remains stopped`.
- [x] 6.3 Bind `no startup command is executed`.
- [x] 6.4 Bind `an authenticated user has selected a Development Chat with a ready checkout and documented Compose workflow`.
- [x] 6.5 Bind `the user clicks Launch beside Expand`.
- [x] 6.6 Bind `startup begins only for that chat without another approval dialog`.
- [x] 6.7 Bind `startup commands and output appear in that chat while execution is in progress`.
- [x] 6.8 Bind `a Development Chat already has a launching or running preview`.
- [x] 6.9 Bind `another Launch request arrives for that chat`.
- [x] 6.10 Bind `no duplicate command sequence or sandbox is created`.
- [x] 6.11 Bind `the existing execution status is returned`.
- [x] 6.12 Bind `a Development Chat's preview has expired after inactivity`.
- [x] 6.13 Bind `the user reloads the chat and opens Context`.
- [x] 6.14 Bind `the previous launch output remains available`.
- [x] 6.15 Bind `the preview remains stopped until another explicit Launch or Restart action`.
- [x] 6.16 Bind `the selected chat's documented Compose watch command is running`.
- [x] 6.17 Bind `the main application begins responding on its resolved entry point`.
- [x] 6.18 Bind `the preview becomes ready without waiting for the watch command to exit`.
- [x] 6.19 Bind `Context displays the application rather than a supporting tool`.
- [x] 6.20 Bind `a Development Chat's database administration tool responds while its application is still starting`.
- [x] 6.21 Bind `readiness is checked`.
- [x] 6.22 Bind `the preview is not marked ready for that tool`.
- [x] 6.23 Bind `startup status continues to describe the application's progress`.

## 7. Step definitions — private application-only forwarding

Adapt the existing preview browser/service gateway and controller forwarding. Register only main-application traffic, not every native Compose port. Preserve owner checks, session stripping, redirects, assets, forms, WebSockets and API-only Swagger behavior.

- [x] 7.1 Bind `a Development Chat's native Compose workflow publishes application, mail tool and database administration ports inside its sandbox`.
- [x] 7.2 Bind `the owner opens the application's registered preview address`.
- [x] 7.3 Bind `the application and its required API requests work through the private gateway`.
- [x] 7.4 Bind `the supporting-tool ports are not registered or listed in Context`.
- [x] 7.5 Bind `a Development Chat has a ready application and a private mail tool in its sandbox`.
- [x] 7.6 Bind `the owner requests the mail tool's localhost port through the preview gateway`.
- [x] 7.7 Bind `the request is rejected without contacting the mail tool`.
- [x] 7.8 Bind `the application's registered route remains available`.
- [x] 7.9 Bind `two Development Chats run applications using the same sandbox-local published port`.
- [x] 7.10 Bind `their owners open their respective registered preview addresses`.
- [x] 7.11 Bind `each address reaches only its owning chat's application`.
- [x] 7.12 Bind `neither sandbox port is exposed directly on the platform host`.

## 8. Step definitions — Launch control and persistent conversation rendering

Update `DevelopWorkspace.tsx`, `DevelopPreview.tsx`, preview API clients and an independent operation-event state path. Merge execution records into conversation history without changing Development Message roles or the Agent Turn reducer. Retain the current desktop/mobile layout and visibility heartbeat behavior.

- [x] 8.1 Bind `an authenticated user has selected a Development Chat with a ready checkout and stopped preview`.
- [x] 8.2 Bind `Launch is available beside Expand`.
- [x] 8.3 Bind `opening Context does not execute startup commands`.
- [x] 8.4 Bind `the conversation remains accessible alongside Context on desktop`.
- [x] 8.5 Bind `the selected chat has a ready checkout and resolvable Docker startup instructions`.
- [x] 8.6 Bind `the user clicks Launch`.
- [x] 8.7 Bind `that chat's startup begins without an approval dialog`.
- [x] 8.8 Bind `Launch indicates progress without allowing another concurrent launch`.
- [x] 8.9 Bind `startup output appears in the conversation while Context remains available`.
- [x] 8.10 Bind `the user opens Context through its mobile control`.
- [x] 8.11 Bind `Launch and Expand remain accessible without horizontal page overflow`.
- [x] 8.12 Bind `launching the application does not remove access to the conversation`.
- [x] 8.13 Bind `a Development Chat's documented Compose workflow starts an application, a mail tool and a database administration tool`.
- [x] 8.14 Bind `the application becomes ready`.
- [x] 8.15 Bind `Context embeds the application`.
- [x] 8.16 Bind `Context does not list or link the supporting tools`.
- [x] 8.17 Bind `a Development Chat has a launching Compose preview`.
- [x] 8.18 Bind `a command emits stdout and stderr before the application becomes ready`.
- [x] 8.19 Bind `its command and both output streams appear incrementally in that chat's execution entry`.
- [x] 8.20 Bind `the output is not presented as an assistant reply or Agent Turn`.
- [x] 8.21 Bind `Context and the conversation remain usable side by side on desktop`.
- [x] 8.22 Bind `a Development Chat has an active preview execution with persisted output`.
- [x] 8.23 Bind `the user refreshes and reopens that chat`.
- [x] 8.24 Bind `the same execution entry and output are restored`.
- [x] 8.25 Bind `new output attaches to that entry without duplicated events or another launch`.
- [x] 8.26 Bind `a Development Chat's initialization command failed and its sandbox was removed`.
- [x] 8.27 Bind `the user revisits the chat`.
- [x] 8.28 Bind `the failed command, redacted diagnostic and exit status remain visible`.
- [x] 8.29 Bind `the interface does not launch a replacement preview automatically`.

## 9. Completion

- [x] 9.1 Run the complete effective acceptance gate with zero failures, pending or undefined steps and an HTML report; preserve source-only regressions where requirements are unchanged.
- [x] 9.2 Verify composition loads no archived, duplicated or superseded auto-start/unsupported-Compose scenarios, and retains the separate responsive-layout/visibility change's scenarios.
- [x] 9.3 Run focused backend/frontend tests for durable events, concurrent launch, chunk-spanning redaction, stream replay, safe output, application routing, sandbox reconciliation and Launch placement.
- [x] 9.4 Verify the demo-like initialization/watch workflow through browser login and item creation, plus two-chat port/name isolation and five-minute cleanup retaining output.
- [x] 9.5 Record deployment privilege policy, dedicated-host/trusted-project prerequisites, privileged-mode risks, verified output/resource bounds and rollback behavior; obtain any separately required authorization before committing code or syncing/archiving specs.

### Verification progress — 2026-11-11

- 191/191 tasks are verified. The final complete effective gate passed all 132 scenarios, including the separate controller-restart scenario; task 9.1 is now checked. Historical partial/failed evidence remains below, followed by the final report and cleanup audit. No code was committed, and specs were not synced or archived.
- `native-compose-restart-network-20261111`: the complete gate assigned 132 scenarios; 113 normal scenarios passed before an over-strict instruction-resolution assertion stopped the run. The instruction resolver is not an Agent Turn. The corrected scenario passed in `native-compose-instruction-diagnosis-20261111` and again in `native-compose-tail-verification-20261111`.
- `native-compose-idle-maintenance-20261111`: the real five-minute idle/output scenario passed with owner-authenticated SSE attached and actual watch output observed in every idle minute. An earlier focused run exceeded six minutes without stopping; this later pass and absence of maintenance warnings do not explain or fix that earlier intermittent failure. Keep the complete gate pending.
- `native-compose-tail-verification-20261111`: five normal scenarios passed before the unsafe fixture failed during native configuration resolution. Its replacement base file had retained an override defining unrelated services without images. The fixture now replaces that override too, without weakening host-access assertions.
- `native-compose-tail-fixed-fixture-20261111`: eight normal scenarios passed, including unsafe-config rejection, initialization/watch sequencing, native configuration, initialization-failure cleanup, browser login/item persistence and effective aggregate kernel limits. The additional service and API process saw the configured CPU/memory/swap/process limits, and actual CPU throttling was observed.
- That run then failed during mobile Launch because Docker Hub rejected the private daemon's Postgres pull with `toomanyrequests` / unauthenticated pull-rate limit. The five remaining normal scenarios and controller-restart scenario were initially unverified. Do not inject registry credentials, broaden acquisition destinations, skip assertions or use the shared daemon to manufacture a green result.
- `native-compose-final-six-20261111`: after public acquisition became available, all five remaining normal scenarios and the controller-restart scenario passed. No credential injection, acquisition-policy change or shared-daemon fallback was used. This verifies the remaining binding tasks; the complete effective gate is still required.
- `native-compose-complete-verification-20261111`: the complete gate freshly assigned all 132 scenarios. It passed 97 normal scenarios, then `Application works without exposing supporting tools` failed when Docker Hub returned its anonymous `toomanyrequests` limit while native watch pulled the mail/admin Python image. The remaining 33 normal scenarios were skipped by fail-fast; the separate controller-restart scenario was not run. The report is failed, not a complete pass, despite every scenario having individual passing evidence across prior runs. Task 9.1 remains blocked on sufficient public-registry acquisition capacity. Do not repeatedly spend full-gate runs while that capacity is unavailable or silently introduce credential injection, mirrors, policy changes or shared-daemon execution.
- Backend services: 345 passed. Frontend: 20 unit tests and 24 preview Chromium tests passed; the frontend build and 13 acceptance-gate self-tests passed. Reports are local HTML/JSON under `acceptance-tests/reports/` with the prefixes above. Deployment policy, verified bounds and rollback are recorded in `deployment-docker-compose.md`.
- The user subsequently authorized a cache integration for testing only, under deterministic-fixture task 1.3 and gate task 9.1. Acceptance-only generated image overlays discover the host daemon's mirror, configure a synthetic private-daemon mirror through the existing Unix acquisition transport, and route registry GET/HEAD to that cache through the trusted helper. Direct Hub fallback and registry writes are rejected. The host cache, production Dockerfiles/runtime/configuration, project socket/network boundaries and credential policy are unchanged. Documentation is in `acceptance-tests/README.md`.
- Local cache/lifecycle/harness regressions: 92 JavaScript tests and 6 Python proxy tests passed. Effective dry-run `native-compose-test-cache-discovery-20261111` freshly assigned the same 132 scenarios and passed discovery/binding checks; it did not start Docker workloads. A real focused acceptance launch was initially denied by the tool permission gate before execution; it was not rerun through another path. These local tests do not satisfy task 9.1 or establish that the private daemon successfully used the cache.
- The user subsequently authorized running the full suite and fixing failures. `native-compose-test-cache-full-20261111` freshly assigned 132 scenarios and failed after 20 normal passes at `Idle preview expires`, before the idle assertion: initialization could not pull the pinned Postgres image. The remaining 110 normal scenarios were skipped and the separate restart scenario did not run. The owned stack was removed and the resource-absence audit passed.
- Real cache use is now established: the shared cache frontend recorded the private daemon's `docker/28.5.1` GET `/v2/` (200) and pinned Postgres manifest GET (500). The cache backend attributed that 500 to `unexpected EOF` fetching Docker Hub's anonymous token endpoint. The test adapter correctly blocked direct Hub fallback. Independent read-only checks reproduced Postgres-manifest HTTP 500 while the cached Python manifest returned 200; a disposable unprivileged Python probe on the cache network reached the anonymous token endpoint with HTTP 200. This is a shared-cache upstream failure, not evidence of a broken idle assertion or missing mirror configuration. No assertions, production code or shared-cache configuration/resources were changed during that run. Task 9.1 remains unchecked.
- The user then explicitly authorized repairing/restarting the shared pull-through cache as test infrastructure, without a new spec change or added test cases. Fresh disposable registry probes could fetch the same Postgres manifest with default settings; compatibility switches were therefore not installed. Restarting only `docker-hub-cache` restored its upstream acquisition without changing configuration, deleting stored layers or changing the `docker-hub-cache-data` volume. After readiness, the pinned Postgres index, Linux/ARM64 manifest, image config and base-layer blob returned HTTP 200 through the existing frontend, with each SHA-256 digest verified. This establishes recovery, not a proven root cause or guarantee against recurrence. All disposable diagnostic registries were removed. The complete gate must still pass.
- `native-compose-cache-recovered-full-20261111` again failed after 20 normal passes before the idle assertion. This time the cache served the Postgres index (200), but rejected its cached OCI platform manifest (404): `OCI manifest found, but accept header does not support OCI manifests`. The acceptance adapter had retained only the first of Docker's repeated Accept header fields. It now combines all Accept values, preserving Docker/OCI negotiation without loosening destination, credential, write or fallback restrictions. Six existing Python and 17 focused JavaScript regressions passed; an ad hoc request carrying separate Docker and OCI Accept fields through the adapter and real cache returned the expected OCI manifest (200) with its digest verified. No new spec or test cases were added. Production files and shared-cache configuration remain unchanged; task 9.1 is still pending.
- `native-compose-cache-accept-fixed-full-20261111` passed 86 normal scenarios, then failed `Refresh and idle expiry do not trigger startup` on its first-minute ongoing-output assertion; 44 later normal scenarios were skipped and the restart group did not run. The real preview did stop, but startup had consumed the first minute of a window anchored before Launch, so the running watch emitted output only in later buckets. Idle fixtures now establish their running-preview baseline through an actual successful browser-generated visible Context heartbeat after readiness, then navigate away and observe five real idle minutes with the same SSE/output-per-minute/cleanup assertions. No clock manipulation, lifetime extension by output, product change or assertion removal was introduced. All 92 existing JavaScript harness and six Python proxy regressions passed after this fixture change. `native-compose-idle-window-fixed-20261111` then passed the complete real `Refresh and idle expiry do not trigger startup` scenario in 479.59 seconds, including five actual idle minutes with ongoing watch output/SSE, cleanup, restored history, no automatic relaunch and a subsequent explicit Launch. This was a one-scenario partial pass, not the complete gate; the final full verification follows.
- `native-compose-idle-and-cache-fixed-full-20261111` passed the complete effective gate in 4958.41 seconds (82 minutes 38 seconds): 132 assigned/reported/passed scenarios, comprising 131 normal scenarios and one separately executed controller-restart scenario. The combined summary reports `status: passed`, `complete: true`, `dryRun: false`, `sourceOnly: false`, no missing scenarios and exit 0 for both groups. All 811 reported step/hook outcomes passed, with zero failed, skipped, pending or undefined outcomes. The effective inventory fingerprint is `2737f28eeb4f96e71b77a2e8418eafee4a368e7015d51ef51cd15de1e5c14edc`. Both final teardown events independently report `ownedResourcesEmpty: true` for projects `sdd-acceptance-93540-391c23b6` and `sdd-acceptance-42077-2e480166`. Combined HTML exists at `acceptance-tests/reports/native-compose-idle-and-cache-fixed-full-20261111-report.html`; summary, results and per-group event reports share that prefix. Task 9.1 is complete. No further code change, commit, sync or archive was performed.
