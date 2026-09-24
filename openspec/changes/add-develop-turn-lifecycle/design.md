## Context

This change follows `add-develop-agent-runner`. Agent execution exists as a bounded operation, but there is no coordinator for concurrent turns, subscribers, disconnect policy, or shared capacity. Port AIDev's `TurnConcurrencyGate`, `TurnSession`, and `DevelopTurnManager` behavior.

## Goals / Non-Goals

**Goals:**

- Enforce one active turn per chat and weighted global admission.
- Support explicit cancellation, timeout, event buffering, and subscribers.
- Apply persisted presence policy and per-user background limits.
- Complete messages and session state consistently.

**Non-Goals:**

- Multi-process or multi-host coordination.
- Network transport for subscriptions.
- Restart-resumable active execution.

## Decisions

### Keep initial coordination process-local

A singleton manager owns daemon-thread execution, turn sessions, grace timers, buffered events, and the weighted gate. The runtime change later constrains deployment to one worker.

Alternative considered: distributed coordination now. It requires a shared event log, durable leases, distributed admission, and shared storage beyond this feature's initial scope.

### Model attachment and presence explicitly

Track subscribers per turn. `Stop when I leave` schedules cancellation after the configured grace period and withdraws it on reattachment. `Continue in background` ignores subscriber loss but consumes a per-user background slot.

Alternative considered: infer presence from HTTP request lifetime. Reattachment and multiple subscribers make that unreliable.

### Centralize terminal completion

One completion path persists scrubbed bounded results, releases capacity, cancels timers, emits terminal state, and removes the active-turn index. Cancellation and timeout converge on the same cleanup path.

Alternative considered: separate cleanup in each exit branch. Resource and state leaks become likely.

## Risks / Trade-offs

- [Backend restart loses active threads] -> Persist completed work only and report stale turns as interrupted after restart.
- [Timer races cancel a reattached turn] -> Guard subscriber and timer transitions under the session lock.
- [Capacity starvation] -> Use weighted FIFO admission and test release behavior.

## Migration Plan

Add turn settings and state objects, implement the gate and manager, integrate completion persistence, then implement the eight scenarios. Rollback disables turn creation and cancels active child processes before removing the manager.

## Open Questions

None.
