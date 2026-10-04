## Why

Checkout-specific startup commands cannot be inferred reliably from file extensions, and the user expects the root README to guide them.

## What Changes

- Pass the selected chat checkout's root README to the Development Chat agent for startup command, local port, and dependency selection.
- If the README lacks instructions, ask the user in chat for commands or a pointer; never invent or silently run undocumented instructions.
- Run resolved commands in that chat's isolated workload without an extra approval step, as agreed.

## Capabilities

### New Capabilities

- `develop-preview-instructions`: Resolve executable preview instructions for one chat checkout.

### Modified Capabilities

None.

## Impact

Agent startup selection, per-chat instruction state and bounded command validation. Depends on private preview workloads.