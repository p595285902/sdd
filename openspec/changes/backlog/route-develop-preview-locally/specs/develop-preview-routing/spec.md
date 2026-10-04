# Develop preview routing

## ADDED Requirements

### Requirement: Only registered chat-local destinations are browsable
The system SHALL translate registered `localhost` ports for the selected Development Chat into its private preview services, including pages, assets, forms and interactive connections, and MUST reject external URLs, unregistered ports and another chat's services.

#### Scenario: Website and Swagger belong to one chat

```gherkin
Given an authenticated user owns a Development Chat with registered website and API ports
When the user requests its website localhost address
Then the website and its assets load only from that chat's service
When the user requests its API localhost Swagger address
Then that chat's Swagger page loads
```

#### Scenario: Unregistered or external address is rejected

```gherkin
Given a Development Chat has a registered website port
When the user requests an external URL or an unregistered localhost port
Then navigation is rejected without contacting that destination
```

#### Scenario: Another chat's service cannot be addressed

```gherkin
Given two Development Chats each have a registered localhost port
When a user requests the first chat's route with the second chat's service address
Then the gateway does not return the second chat's preview content
```