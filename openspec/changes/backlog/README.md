# Develop Context preview backlog

These are complete planning artifacts parked for sequential implementation. The acceptance extractor intentionally does not load specs inside `changes/backlog/<name>/`, so the only active preview change is `detect-develop-preview-changes`.

## Promotion order

Each entry has `.openspec.yaml`, `proposal.md`, `design.md`, `tasks.md`, and a capability delta spec. Implement them one at a time, targeting a work slice under one hour:

1. `classify-develop-preview` - website/Swagger classification helper.
2. `isolate-develop-preview-controller` - private resource-bounded chat workload.
3. `expire-develop-preview-workloads` - restart, deletion and five-minute idle cleanup.
4. `resolve-develop-preview-instructions` - root README commands and chat fallback.
5. `trigger-develop-preview-startup` - first Context opening, relevant turns and initial page.
6. `support-develop-preview-compose` - optional existing Compose and dependent API.
7. `authorize-develop-preview-browser` - separate origin and short-lived browser auth.
8. `route-develop-preview-locally` - chat-local localhost port routing.
9. `browse-develop-preview-in-context` - interactive browser and navigation.
10. `expand-develop-preview-context` - responsive expansion and visibility heartbeats.

## Promoting a change

After the preceding change has passed the full acceptance suite and its delta has been synced and archived, move one child directory from `openspec/changes/backlog/<name>/` to `openspec/changes/<name>/`. Then run `openspec status --change <name>`, `openspec validate <name>`, and the spec linter before implementation. OpenSpec only recognizes direct children of `changes/`; `openspec list` reports this parent folder as an organizational pseudo-change. Its `.openspec.yaml` uses `skip_specs: true` solely to keep `openspec validate --all` usable while the child plans are parked.

These are time-boxing targets, not guarantees. Recheck scope during promotion, especially the Docker controller, Compose and browser gateway; split a change further if its implementation and acceptance checks cannot fit within one hour. No backlog spec is executable until promoted.