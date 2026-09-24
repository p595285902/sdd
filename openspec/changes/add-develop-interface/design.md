## Context

This change follows `add-develop-streaming-api`. A minimal Develop route exists from the foundation, and backend contracts now support workspace setup and streamed turns. The reference UI behavior is in AIDev's `DevelopWorkspace.tsx`, API adapter, and components.

## Goals / Non-Goals

**Goals:**

- Deliver a native shadcn/TanStack exploration workspace.
- Adapt chat caching, history, stream lifecycle, reattachment, optimistic messages, and bounded activity.
- Provide responsive access to history, conversation, context, setup, stop, and presence controls.

**Non-Goals:**

- Bootstrap or Django template reuse.
- Proposal approval and apply controls.
- Repository selection or collaboration.

## Decisions

### Port behavior into the target component system

Use an unframed three-column desktop layout for history, conversation, and context. Narrow screens retain conversation as the primary view with explicit history and context controls. Reuse existing shadcn components and Lucide icons.

Alternative considered: transplant Bootstrap markup. It conflicts with the established design language and build system.

### Isolate the hand-written stream adapter

Generated client operations handle JSON. One Develop adapter parses fetch-based SSE, validates normalized events, and hands them to workspace state. Raw HTML remains disabled in the maintained Markdown renderer.

Alternative considered: mix parsing into components. That spreads protocol details and makes reattachment difficult to test.

### Preserve stable conversation behavior

Maintain a bounded five-chat cache, optimistic user messages, pinned scrolling unless the user moves away, incremental older history, elapsed time, expandable activity, and replay-aware deduplication.

## Risks / Trade-offs

- [Optimistic and replayed messages duplicate] -> Reconcile by persisted IDs and turn identity.
- [Long activity shifts layout] -> Bound content and expand it within stable regions.
- [Responsive controls hide state] -> Keep running status and Stop available in the primary flow.

## Migration Plan

Add Markdown dependency and API adapter, replace the minimal shell incrementally, add component and Playwright coverage, then implement the streamed exploration scenario. Rollback restores the minimal route while retaining backend capabilities.

## Open Questions

None.
