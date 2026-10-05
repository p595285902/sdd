## 1. Instruction resolution

- [ ] 1.1 Add a bounded agent instruction result using the root README and chat-local file pointers; test ordered dependency and website/API commands, working directories, ports, untrusted README text and symlink/path confinement.
- [ ] 1.2 Ask in chat for missing, ambiguous or unsupported instructions (including Compose and `.env` sourcing), retain a per-chat answer and never execute guessed or unsupported commands.

## 2. Private workload execution

- [ ] 2.1 Provide and pin a preview image with shell, Python/uv and Node.js/npm/Bun; test tool availability, non-root execution, resource limits, missing secrets/socket, no host ports and two-chat checkout isolation.
- [ ] 2.2 Add bounded dependency/setup execution with allowlisted registry acquisition or cache, chat-scoped writable checkout/build/dependency storage and scratch space; test successful install, denied host/private/backend network access, path escapes and unsupported dependency sources.
- [ ] 2.3 Start documented website and API processes in the same workload, check both HTTP services on localhost, enforce port/startup time bounds and redacted error reporting; test intra-workload API access and cleanup on failure, expiry and deletion.

## 3. Acceptance

- [ ] 3.1 Implement acceptance steps for real documented non-Compose dependency installation and website/API responses inside the workload, missing instructions, unsupported Compose, localhost isolation and timeout cleanup; run the focused tests red then green.
- [ ] 3.2 Run the full acceptance suite with zero pending steps and an HTML report; do not implement later Compose, startup trigger or browser gateway work in this change.