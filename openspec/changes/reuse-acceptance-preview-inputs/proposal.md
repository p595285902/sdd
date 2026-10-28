## Why

The acceptance suite already reuses its backend, but preview scenarios still create chat-owned workloads and repeat preview setup. Reusing verified, immutable preparation within one run may reduce effective full-suite time without sharing live preview state between chats.

## What Changes

- Measure preview workload creation, dependency preparation, and image build time in the effective acceptance suite before optimizing.
- Reuse prepared preview inputs only when the complete relevant build and dependency inputs match, within one isolated acceptance run.
- Keep each scenario's chat-owned preview workload fresh and preserve restart, deletion, isolation, and teardown behavior.
- Compare effective full-suite elapsed time with the historical reference, while distinguishing it from a matched before/after benchmark.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `acceptance-stack-reuse`: Permit reuse of identical prepared preview inputs across chats within a run, while retaining fresh chat-owned workloads and run-scoped cleanup.

## Impact

Acceptance preview fixtures and run lifecycle, and potentially the preview controller's acceptance-only preparation path if harness-only reuse cannot reach the measured bottleneck. No production preview behavior, API contract, new dependencies, or cross-run warm stack is intended.
