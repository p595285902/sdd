# Develop preview browser auth

## ADDED Requirements

### Requirement: Browser preview access is isolated and chat-owned
The system SHALL serve preview pages from a separate origin that does not share application storage or credentials, SHALL issue a short-lived browser credential only to the owning user, and MUST validate current chat ownership on every preview request without exposing the app bearer token to the page.

#### Scenario: Owner gets a chat-bound browser session

```gherkin
Given an authenticated user owns a Development Chat with a ready preview
When the user requests browser access for that chat
Then access is bound to that chat and expires after a short period
And the preview page receives no application bearer token
```

#### Scenario: Another user or deleted chat is denied

```gherkin
Given a Development Chat has a browser preview session
When a different user or a deleted chat requests its preview
Then access is denied without disclosing preview content
```