## Context

The controller can start private workloads from documented commands. Some checkouts have an existing Compose graph; unchecked Compose options could escape preview isolation.

## Goals / Non-Goals

**Goals:** Run documented dependencies in a private project without changing the checkout.

**Non-Goals:** Generate a Compose definition or support privileged/host-networked services.

## Decisions

- Resolve an existing Compose file only when explicitly called out by the root README. Give every chat a unique project name and network; select documented services with their dependencies. If no documented file exists, use ordinary startup commands.
- Validate the resolved Compose model with structured tooling before launch; deny privileged options, host networking, Docker socket mounts, out-of-checkout host mounts and public port publishing. Fail visibly rather than weakening isolation or rewriting a checked-out file.

## Risks / Trade-offs

- Some Compose files require forbidden host settings; those previews fail safely until the user supplies compatible instructions.