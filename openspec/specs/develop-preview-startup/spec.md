# Develop preview startup

## Purpose
Start chat-specific previews when Context first needs them or a relevant Agent Turn finishes, while preserving healthy servers and reporting a useful initial page and status.

## Requirements

### Requirement: Preview starts when the selected checkout needs it
The system SHALL start the original ready checkout on first Context opening, SHALL start a stopped preview after a completed Agent Turn changes non-ignored files, and MUST NOT restart a healthy server for an ignored-only edit. A running server SHALL remain available for hot reload.

#### Scenario: First Context visit starts the original checkout

```gherkin
Given a Development Chat has a ready checkout and resolved startup instructions
When the user opens Context before any file-changing Agent Turn
Then that chat's original checkout starts for preview
```

#### Scenario: Relevant turn starts a stopped preview

```gherkin
Given a Development Chat has a stopped preview and resolved startup instructions
When an Agent Turn completes after changing a non-ignored source file
Then that chat's preview starts
```

#### Scenario: Ignored edit does not restart a healthy preview

```gherkin
Given a Development Chat has a healthy running preview
When an Agent Turn completes after changing only ignored files
Then its running preview remains available for hot reload
```

### Requirement: Startup status and initial page reflect the selected checkout
The system SHALL report starting, ready, stopped, unavailable and failed startup status for the owning Development Chat and SHALL select its website as the initial page when runnable, or its Swagger page for an API-only checkout.

#### Scenario: API-only preview opens Swagger

```gherkin
Given a Development Chat has an API-only checkout with documented Swagger startup
When that chat's preview becomes ready
Then the initial preview page is its Swagger page
```