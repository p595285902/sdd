# Develop preview routing

## ADDED Requirements

### Requirement: Only the application is exposed from a native Compose sandbox
The system SHALL register only the selected chat's main application entry point and any website/API routes necessary for that application to function. An API-only application's documented Swagger entry point SHALL remain supported. Native Compose port publication SHALL terminate inside the private sandbox and MUST NOT automatically register database ports, mail tools, database administration tools, Docker daemon ports or arbitrary supporting services with the preview gateway. Application forwarding SHALL preserve owner authentication, assets, forms, redirects and interactive connections without giving the application platform session credentials or a general connection to the platform network. The gateway MUST reject unregistered supporting-service destinations even for the chat owner.

#### Scenario: Application works without exposing supporting tools

```gherkin
Given a Development Chat's native Compose workflow publishes application, mail tool and database administration ports inside its sandbox
When the owner opens the application's registered preview address
Then the application and its required API requests work through the private gateway
And the supporting-tool ports are not registered or listed in Context
```

#### Scenario: Owner cannot browse a private auxiliary port

```gherkin
Given a Development Chat has a ready application and a private mail tool in its sandbox
When the owner requests the mail tool's localhost port through the preview gateway
Then the request is rejected without contacting the mail tool
And the application's registered route remains available
```

#### Scenario: Equal application ports route to different chat sandboxes

```gherkin
Given two Development Chats run applications using the same sandbox-local published port
When their owners open their respective registered preview addresses
Then each address reaches only its owning chat's application
And neither sandbox port is exposed directly on the platform host
```
