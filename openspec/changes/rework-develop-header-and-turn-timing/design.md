## Context

The Develop workspace currently places repository readiness and two Presence Mode buttons in the Context sidebar. The chat header already owns setup, rename, and delete actions. Its streaming response displays a client-side elapsed timer, but persisted Development Messages store activity without duration, so a completed response loses its timing on reload. The TurnSession is process-local, and assistant messages are persisted by the Develop routes.

## Goals / Non-Goals

**Goals:** Keep all chat actions accessible in a wrapping header, retain the Context panel with an empty state, and display both live and durable completed Agent Turn timing beside "Agent activity".

**Non-Goals:** Replace the Context panel, connect user-owned repositories, backfill historic turn durations, or change Presence Mode semantics.

## Decisions

1. Put the rename icon in the title group and repository status/setup, Presence Mode, and Delete in an action group that wraps below the title on small screens. Use the existing Select and Tooltip primitives, a colored repository icon with accessible status text, and the existing setup and presence mutations. Yellow represents an in-flight setup mutation, green a ready workspace, and red setup required; an unavailable setup action remains disabled with an explanatory tooltip. Keep the Context sidebar and mobile entry point with a "No additional context" empty state. Alternative: remove the sidebar; rejected because it must remain available.
2. Add a nullable, nonnegative `duration_seconds` to Development Messages and their public response, populated only on assistant messages created for a completed Agent Turn. Compute elapsed time on the server from a monotonic timestamp captured at turn admission to the assistant-message completion point, rounding for a stable display. Use a nullable additive database migration and regenerate the TypeScript API client. Alternative: calculate from message creation timestamps or keep the duration in client cache; neither reliably represents turn runtime after a reload.
3. Continue the client-side ticking timer during streaming and display it beside the existing "Agent activity" label. For persisted assistant messages, format `duration_seconds` in the same minute:second style; omit duration for older messages without a value. When streaming gives way to persisted history, prefer the server-recorded final duration. Alternative: continue displaying the client counter after completion; that would be lost on reload and could drift from server time.

## Risks / Trade-offs

- [Disabled setup controls can suppress tooltips] -> Attach the tooltip to a non-disabled wrapper, keep the status accessible as text, and verify hover/focus states.
- [Client and server timers may differ slightly] -> Treat the server-recorded duration as authoritative on persisted messages.
- [Historical messages lack timing] -> Preserve them with a nullable field and render activity without a duration.
- [Failures before an assistant message is stored have no completed response to annotate] -> Do not fabricate history entries; keep existing error reporting behavior.

## Migration Plan

Add the nullable duration column before deploying writers, then extend message serialization and generated client types. The migration does not backfill old rows; rollback removes the column only after code stops depending on it. Validate backend persistence, frontend rendering at desktop/mobile widths, and the acceptance suite during implementation.

## Open Questions

None.