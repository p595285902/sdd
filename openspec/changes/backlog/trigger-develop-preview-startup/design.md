## Context

The preceding slices expose per-turn file-change signals, content classification, command resolution and chat-private workloads. No startup trigger ties them together yet.

## Goals / Non-Goals

**Goals:** Start on first Context use and relevant turns, keep healthy servers, report status and select an initial page.

**Non-Goals:** Compose orchestration, browser routing or Context UI rendering.

## Decisions

- Expose an owner-checked startup/status endpoint for initial Context opening. Dispatch the same idempotent startup operation after a successful, relevant file-changing turn. User-supplied instructions resume a waiting startup without another file edit.
- Return an explicit per-chat status model and registered service port/initial path. Prefer website, otherwise documented Swagger; never show another chat's status or page. Retain healthy processes for hot reload, restart only after failure or user request.

## Risks / Trade-offs

- Command execution may outlive a web request; limit startup time and persist status for reconnection.