## Context

The controller can start private workloads from documented commands. Some checkouts have an existing Compose graph; unchecked Compose options could escape preview isolation.

## Goals / Non-Goals

**Goals:** Run documented dependencies in a private project without changing the checkout.

**Non-Goals:** Generate a Compose definition or support privileged/host-networked services.

## Decisions

- Resolve an existing Compose file only when explicitly called out by the root README. Give every chat a unique project name and network; select documented services with their dependencies. If no documented file exists, use ordinary startup commands.
- Keep the Docker API and a pinned Compose parser/adapter in the trusted controller, never in the checkout or preview containers. Resolve the complete Compose model with a scrubbed environment and no checkout-supplied `.env`, then validate every selected service and transitive dependency before any build, pull or container creation. Reject unsupported interpolation, includes, external files, image sources and options rather than passing unchecked configuration to Docker. Do not rewrite the checked-out Compose file.
- Stage only validated checkout-local, symlink-confined build inputs into a per-chat private build context. Build with no general network and no secrets; allow package downloads only through the existing registry allowlist proxy or a bounded cache. Reject builds requiring other egress or host resources. Pull only explicitly allowed images through the trusted adapter. Neither Compose nor a Docker socket runs inside the preview workload.
- Create a chat-unique internal network for the website and all required dependencies. Services communicate by Compose service name; no service publishes a host port or joins the backend, host, another chat's network or a user-declared external network. The trusted controller checks readiness on the private network, registers only documented website/API ports for later browser routing and leaves that later browser gateway out of this change.
- Apply non-root execution, dropped capabilities, read-only roots with bounded writable scratch/storage, CPU, memory, PID and lifetime limits to every service, including build and setup processes. Reject privileged, host namespace, device, Docker socket, arbitrary bind/volume, extra-host, secret, credential, port publishing or custom network settings that cannot be proven to preserve those limits; never forward backend environment variables. An unsupported Compose model asks for compatible instructions instead of weakening the policy.
- Track all images, containers, networks and bounded storage by the chat-unique project identity; remove only that project's resources on startup failure, restart, chat deletion or expiry. Preserve ordinary non-Compose startup and cleanup unchanged.

## Risks / Trade-offs

- Some Compose files require forbidden host settings, persistence, unapproved images or unrestricted build-time egress; those previews fail safely until the user supplies compatible instructions. A private Docker network alone is not an egress firewall; enforce isolation at the Docker/network boundary and verify attempted host, private-network and backend access in tests.
- Validate the whole dependency graph before launch: a safe website service does not make an unsafe API or database dependency safe. Apply the same quota and cleanup checks to each service so multi-service graphs cannot evade single-workload limits.