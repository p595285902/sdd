## Context

The preceding change starts private workloads but does not stop them automatically. The existing delete endpoint already removes a chat's checkout.

## Goals / Non-Goals

**Goals:** Bounded lifecycle, idempotent restart, owner-specific cleanup and deterministic idle tests.

**Non-Goals:** Browser UI or command selection.

## Decisions

- Track last visible activity by chat; receive bounded heartbeats from the later Context UI. A controller-side clock stops an idle workload after five minutes, including when the browser disconnects. Reconcile chat ownership after controller restarts.
- Invoke idempotent stop during chat deletion before workspace cleanup; restart replaces only the matching chat-labeled workload. Test with a fake clock and two chats.

## Risks / Trade-offs

- An open but hidden tab must not keep the preview alive; the UI sends heartbeats only when visible.