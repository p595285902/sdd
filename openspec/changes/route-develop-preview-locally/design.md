## Context

The preceding browser-auth change protects a separate preview origin; the startup controller registers private chat services. Raw client localhost means the user's computer, not the server's container.

## Goals / Non-Goals

**Goals:** Make displayed localhost addresses mean registered ports of the selected chat and preserve interactive website behavior.

**Non-Goals:** General web browsing or publicly published container ports.

## Decisions

- Bind each registered port to exactly one chat-owned private service. Translate `http://localhost:<port>/<path>` via the separate authenticated origin. Reject user-controlled upstream hosts, Host header overrides, external redirects and unregistered ports before forwarding.
- Preserve assets, forms, WebSockets and Swagger documents under the routed origin. Never forward browser credentials or app tokens to the preview app as arbitrary headers; verify chat ownership on each request.

## Risks / Trade-offs

- Apps with hard-coded absolute URLs may need origin mapping; test an actual frontend with hot reload and Swagger before relying on path-only routing.