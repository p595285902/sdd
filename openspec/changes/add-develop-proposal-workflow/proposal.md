## Why

After exploration is usable, users need an explicit approval boundary between discussing a change and applying it. This change follows `add-develop-interface` and adds only the propose, approve, reject, and apply workflow.

## What Changes

- Generate an OpenSpec proposal from the canonical stored Development Chat conversation.
- Persist proposal messages with an undecided, approved, or rejected decision.
- Atomically approve one undecided proposal and start one weighted apply Agent Turn.
- Reject an undecided proposal without starting an apply turn.
- Confine apply changes to the owning Development Workspace and never publish remotely.
- Add Make it happen, Approve, and Reject controls and conflict handling.

## Capabilities

### New Capabilities

- `develop-proposal-workflow`: Proposal generation, explicit decision state, approved apply execution, and workspace-only modification boundaries.

### Modified Capabilities

None.

## Impact

- Proposal persistence, agent prompts, decision endpoints, turn weighting, frontend controls, and end-to-end tests.
- Requires `add-develop-interface` to be implemented first.
