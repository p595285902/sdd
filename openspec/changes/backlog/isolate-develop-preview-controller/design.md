## Context

The backend currently owns per-chat checkout paths but no long-lived preview controller. Executing README commands in that backend would expose application secrets.

## Goals / Non-Goals

**Goals:** Introduce an isolated single-chat workload primitive with inspectable status.

**Non-Goals:** README command discovery, Compose workflows, idle expiry, or page routing.

## Decisions

- A trusted controller, separate from the backend and the workload, holds Docker access. The backend requests operations by chat ID; the preview workload never sees Docker control or backend secrets. Do not mount the host Docker socket into the API or preview container.
- Restrict mounts to the validated checkout; deny host networking, public ports and privileged mode; set CPU, memory and process limits. Label workloads by chat ID for subsequent lifecycle management.

## Risks / Trade-offs

- Docker access is privileged even for a controller. Restrict its API and deployment authority before enabling arbitrary checkout execution.