## Context

The initial browser sits in the existing 17rem Context column. The runtime already exposes a five-minute idle timer driven by visible-panel activity.

## Goals / Non-Goals

**Goals:** Wider responsive preview and accurate visibility heartbeat.

**Non-Goals:** Change startup commands, external navigation or chat history behavior.

## Decisions

- Offer a desktop expand/collapse control and a mobile full-width Context view while retaining a route back to chat. Keep browser dimensions stable and avoid nested card layout.
- Send a bounded heartbeat only when Context is open and `document.visibilityState` is visible. Stop on close, chat switch or unmount; the controller expires previews after five minutes without it.

## Risks / Trade-offs

- Mobile overlays and desktop resizing can cause focus loss; verify keyboard navigation and screenshot layout at both widths.