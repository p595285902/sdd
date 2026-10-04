## Context

Each Development Chat has a checkout under `DEVELOP_WORKSPACE_ROOT/<chat_id>`. The current turn completion path persists the response but does not retain a file-change signal. Candidate classification and preview startup are later changes.

## Goals / Non-Goals

**Goals:** Detect per-turn relevant changes without mixing chats.

**Non-Goals:** Classify website/API content, execute README commands, start servers, expose preview URLs, or alter Context UI.

## Decisions

- Keep ignore rules in an application-owned file outside the checked-out repository, with `openspec/`, `.claude/`, `.git/`, dependencies and generated output excluded by default. Match normalized paths relative to the validated workspace root; never accept ignore overrides from the checkout.
- Capture a bounded file-state snapshot before and after each successful exploration turn to detect both tracked edits and new files, including changes to already-dirty workspaces. Compare only within that turn and apply ignore rules before reporting the event to the later orchestrator. Avoid using `git status` alone, since prior uncommitted changes would look new on subsequent turns.

## Risks / Trade-offs

- Large checkouts can make snapshots expensive; skip ignored/generated trees and cap scans with a clear unavailable result instead of blocking turn completion indefinitely.

## Sequential follow-up changes

Propose and implement these one at a time, each scoped to roughly 30-55 minutes; only activate the next delta after the current acceptance suite is green and its delta has been synced and archived. None of these future requirements are active in this proposal:

1. `classify-develop-preview`: A helper for connected HTML and JavaScript/TypeScript website entry points, framework projects, and API-only Swagger candidates; avoid unrelated-file false positives.
2. `isolate-develop-preview-controller`: A trusted Docker controller boundary and one resource-bounded per-chat container without backend secrets, host control socket, host ports, or other chats' checkouts.
3. `expire-develop-preview-workloads`: Chat deletion/restart cleanup and five-minute inactivity stop; visible Context activity keeps a workload alive.
4. `resolve-develop-preview-instructions`: Read the root README through the agent; ask the user in chat for a command or pointer if absent. No command approval and no guessed instructions.
5. `trigger-develop-preview-startup`: Start on first Context opening or completed relevant turn; keep healthy servers for hot reload and provide startup/failed/ready status and website-versus-Swagger default.
6. `support-develop-preview-compose`: Use only README-described existing Compose files, start required website and API services in chat-unique private projects, validate unsafe settings, retain non-Compose startup, and never generate a file.
7. `authorize-develop-preview-browser`: Short-lived chat-bound browser credentials on a separate preview origin, ownership checked per request, no app bearer token in the page.
8. `route-develop-preview-locally`: Translate registered chat-local localhost ports for pages, assets, forms and WebSockets, rejecting external/unknown destinations and cross-chat access.
9. `browse-develop-preview-in-context`: Replace the static panel with an interactive browser, local address bar, history/reload/restart controls and explicit empty/loading/error states; modify the existing develop-interface requirement in full.
10. `expand-develop-preview-context`: Expandable desktop/mobile view and visible-only activity heartbeat, with focused browser and acceptance coverage.