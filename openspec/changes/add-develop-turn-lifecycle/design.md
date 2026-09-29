## Context

This change follows `add-develop-agent-runner`. Agent execution exists as a bounded operation, but there is no coordinator for concurrent turns, subscribers, disconnect policy, or per-user capacity. Port AIDev's `TurnSession` and `DevelopTurnManager` behavior while adapting admission to the target's per-user limit.

## Goals / Non-Goals

**Goals:**

- Enforce one active turn per chat and a configurable concurrent active-turn limit per user, defaulting to two.
- Support explicit cancellation, timeout, event buffering, and subscribers.
- Apply persisted presence policy and bound background execution with the turn timeout.
- Complete messages and session state consistently.

**Non-Goals:**

- Multi-process or multi-host coordination.
- Network transport for subscriptions.
- Restart-resumable active execution.

## Decisions

### Keep initial coordination process-local

A singleton manager owns daemon-thread execution, turn sessions, grace timers, buffered events, and per-user active-turn counts. The runtime change later constrains deployment to one worker.

Alternative considered: distributed coordination now. It requires a shared event log, durable leases, distributed admission, and shared storage beyond this feature's initial scope.

### Model attachment and presence explicitly

Track subscribers per turn. `Stop when I leave` schedules cancellation after the configured grace period and withdraws it on reattachment. `Continue in background` ignores subscriber loss and remains bounded by the configured turn timeout.

Alternative considered: infer presence from HTTP request lifetime. Reattachment and multiple subscribers make that unreliable.

### Count concurrent active turns per user

Each active Agent Turn consumes one slot from its owner's configured concurrent-turn limit across Development Chats. The limit defaults to two and can be configured for each user. Starting a turn reserves a slot atomically; when no slot is available, the manager rejects the request immediately with a reason instead of queueing it. Terminal completion releases the slot.

Alternative considered: a weighted process-wide gate with queued admission. It couples unrelated users, obscures the simple user-facing limit, and delays requests that should receive an actionable rejection.

### Centralize terminal completion

One completion path persists scrubbed bounded results, releases capacity, cancels timers, emits terminal state, and removes the active-turn index. Cancellation and timeout converge on the same cleanup path.

Alternative considered: separate cleanup in each exit branch. Resource and state leaks become likely.

## Risks / Trade-offs

- [Backend restart loses active threads] -> Persist completed work only and report stale turns as interrupted after restart.
- [Timer races cancel a reattached turn] -> Guard subscriber and timer transitions under the session lock.
- [Concurrent starts exceed a user's limit] -> Reserve and release per-user slots under the manager lock and test simultaneous requests.

## Migration Plan

Add turn settings and state objects, implement the gate and manager, integrate completion persistence, then implement the eight scenarios. Rollback disables turn creation and cancels active child processes before removing the manager.

## Open Questions

None.
