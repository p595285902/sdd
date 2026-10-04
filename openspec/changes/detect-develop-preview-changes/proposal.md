## Why

The Develop Context panel will need to react to relevant changes in a chat's checkout. Without a per-turn signal, edits to agent metadata or ignored files could trigger needless preview starts.

## What Changes

- Record relevant file changes made by completed Agent Turns, excluding paths from an application-owned ignore file, including `openspec/` and `.claude/`.
- Expose the change signal to later preview orchestration without classifying the repository or launching a server in this change.

## Capabilities

### New Capabilities

- `develop-preview-detection`: Report preview-relevant changes after a chat's Agent Turns.

### Modified Capabilities

None.

## Impact

Backend Develop workspace and turn completion services, application-owned ignore configuration, and focused backend tests. No website helper, preview runtime, or Context UI yet.