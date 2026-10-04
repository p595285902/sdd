## Why

Preview startup needs to know whether the selected checkout is a website, an API with Swagger, or neither. Unrelated HTML and script files are not enough to prove a runnable website.

## What Changes

- Add a checkout-scoped classification helper for connected HTML and JavaScript/TypeScript website entry points, including framework projects.
- Identify documented Swagger/OpenAPI candidates when no website is found; return unknown when evidence is insufficient.
- Do not start servers or parse README commands in this change.

## Capabilities

### New Capabilities

- `develop-preview-classification`: Classify a chat's checkout for its initial preview page.

### Modified Capabilities

None.

## Impact

Backend Develop workspace helper and focused tests. Follows `detect-develop-preview-changes`.