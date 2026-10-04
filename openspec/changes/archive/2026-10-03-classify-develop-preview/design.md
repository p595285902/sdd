## Context

Each Development Chat already has an isolated checkout. File-change detection does not decide what kind of application that checkout contains.

## Goals / Non-Goals

**Goals:** Return a candidate type and initial-page evidence scoped to a validated chat path.

**Non-Goals:** Guarantee startup, run commands, or trust arbitrary HTML/script pairs.

## Decisions

- Add a small backend classifier that looks for connected web entry points or a framework application manifest, not merely file extensions anywhere in the tree. API documentation evidence is separate; website wins when both exist.
- Return unknown for ambiguous checkouts. The later README startup resolver confirms the port and actual page before showing it.

## Risks / Trade-offs

- Custom build systems can escape detection; user-provided startup instructions can still make them previewable later.