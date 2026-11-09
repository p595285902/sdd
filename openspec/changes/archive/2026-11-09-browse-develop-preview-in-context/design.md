## Context

The existing Context `aside` is a static placeholder and opens as a mobile overlay. The preceding changes provide Compose startup/status, chat-local routing and browser authorization. This change integrates only Compose-based checkouts.

## Goals / Non-Goals

**Goals:** Interactive Compose website or Swagger preview with address entry, Reload and Restart on desktop/mobile. Preserve chat-scoped localhost routing while allowing external navigation. Provide the same live activity and response streaming behavior across Explore, Propose and Apply.

**Non-Goals:** Preview history, Back/Forward controls, tracking in-frame navigation, external-navigation containment, agent automation, non-Compose preview integration or restart fixes, and expanded layout (next change).

## Decisions

- Show a separate-origin iframe controlled by a small toolbar: address entry, Reload and Restart. Translate registered localhost addresses to the selected chat's service origins using the existing gateway; do not add history storage or a navigation-reporting bridge. The address field shows the requested preview address, without tracking subsequent in-frame navigation.
- Allow normal browser navigation to external destinations; these requests go directly to the destination, not through the chat's localhost gateway.
- Replace the iframe on chat switch before requesting the next chat's browser session. Render startup, missing instructions, stopped and failure states instead of stale pages. This protects chat selection without restricting where users browse inside the iframe.
- Reuse existing Compose startup and restart behavior. Non-Compose runtime changes are deferred and are not prerequisites for this implementation.
- Use the same Agent Turn streaming contract and activity/response rendering for Explore, Propose and Apply. Proposal generation must deliver live activity and partial response text instead of returning only a completed result. Preserve proposal approval/rejection controls once the proposal is stored. The existing Explore scenario and a Propose/Apply scenario outline use identical acceptance steps to verify the same streaming behavior across all three workflows.

## Risks / Trade-offs

- A fixed narrow sidebar constrains some sites until the subsequent expandable-layout change; preserve the mobile entry point meanwhile.
- The address field does not follow links, redirects or SPA navigation inside the iframe; navigation tracking is intentionally deferred.
- External sites may refuse embedding through their own browser policies; allowing navigation does not bypass those policies.
