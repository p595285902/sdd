## Why

Checkout-specific startup commands cannot be inferred reliably from file extensions, and the user expects the root README to guide them. The current private preview workload cannot install dependencies or run a documented website and API: its checkout is read-only, its image has only Python, and networking is disabled.

## What Changes

- Pass the selected chat checkout's root README to the Development Chat agent for dependency setup, startup commands, working directories and local port selection. Follow chat-local pointers only inside that checkout.
- Equip the private workload with documented Python and JavaScript tooling and bounded, checkout-local writable build/dependency space so supported website and API commands actually run. Permit only constrained package acquisition and communication between services on localhost inside that workload; retain CPU, memory, process and lifetime limits, and no host ports, backend secrets, Docker socket or other chat's files.
- If the README lacks usable instructions or requires unsupported facilities, ask in chat for supported commands or a pointer; never invent or silently run undocumented or unsafe instructions.
- Run supported resolved commands in that chat's isolated workload without an extra approval step, as agreed; report startup/health failures and clean up stopped or expired processes.

## Capabilities

### New Capabilities

- `develop-preview-instructions`: Resolve executable preview instructions for one chat checkout.

### Modified Capabilities

None.

## Impact

Agent startup selection, per-chat instruction state, bounded execution and focused acceptance tests. Extends the private preview workload without granting host privileges. Does not implement Compose orchestration, startup triggers or authenticated browser routing; a Compose-only README is not executable in this change.