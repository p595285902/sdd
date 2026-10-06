## 1. Optional Compose

- [ ] 1.1 Select only README-described, existing Compose files; resolve and validate every selected service and dependency with pinned trusted tooling before any resource is created. Test unsupported options, interpolation and transitive unsafe dependencies.
- [ ] 1.2 Stage symlink-confined, bounded checkout-local build inputs and restrict builds, image pulls and dependency downloads to permitted sources; test out-of-checkout inputs and denied host/private/backend access.
- [ ] 1.3 Start all required services with private chat-unique networks, service-name access, no host ports/secrets/socket, and per-service CPU/memory/PID/storage/lifetime limits; preserve non-Compose startup.
- [ ] 1.4 Clean up only the owning chat's containers, network and storage on startup failure, restart, deletion and expiry; test two-chat isolation.

## 2. Acceptance

- [ ] 2.1 Implement multi-service, missing-Compose, unsafe-config, build-source, network-isolation and lifecycle steps red then green; run the full acceptance suite with zero pending steps and an HTML report.