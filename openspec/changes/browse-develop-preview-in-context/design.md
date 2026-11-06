## Context

The existing Context `aside` is a static placeholder and opens as a mobile overlay. The preceding backlog changes provide status, chat-local routing and browser authorization.

## Goals / Non-Goals

**Goals:** Interactive, local-only preview with navigation and restart on desktop/mobile.

**Non-Goals:** Agent automation, arbitrary websites or expanded layout (next change).

## Decisions

- Show a separate-origin iframe controlled by a small browser toolbar: local URL entry, Back, Forward, Reload and Restart. Validate registered localhost addresses before navigation. Gateway-managed history avoids reading cross-origin iframe internals.
- Replace the iframe on chat switch before requesting the next chat's browser session. Render startup, missing instructions, stopped and failure states instead of stale pages.

## Risks / Trade-offs

- A fixed narrow sidebar constrains some sites until the subsequent expandable-layout change; preserve the mobile entry point meanwhile.