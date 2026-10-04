## Context

The frontend stores API bearer auth in local storage. An iframe and its subresources cannot attach that header, while same-origin untrusted pages could access app storage.

## Goals / Non-Goals

**Goals:** Authenticated browser access on a separate origin, with no app bearer token in the preview.

**Non-Goals:** Route arbitrary destinations or render the Context UI.

## Decisions

- Add a dedicated preview origin configured per deployment; fail closed without it. An authenticated app API issues a short-lived, one-chat browser session. A scoped credential on the preview origin authenticates page/asset requests without placing the API bearer token in page content or the URL.
- Verify current user/chat ownership for every request, not just credential issuance; invalidate sessions on chat deletion or expiry. Set narrow frame policy and cookie scope.

## Risks / Trade-offs

- Cross-origin browser cookie policies differ by deployment. Exercise the iframe flow on the configured dev and production origins before enabling it.