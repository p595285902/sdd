# Develop preview Compose

## ADDED Requirements

### Requirement: Documented Compose workflows start per chat
The system SHALL use an existing Compose file only when the selected checkout's root README calls for it. It SHALL start all services required by the website, including its API, under a private chat-unique project without public ports or host control access, and MUST NOT generate a Compose file.

#### Scenario: Website requires an API service

```gherkin
Given a Development Chat checkout has a README describing an existing Compose file with website and API services
When that chat's preview starts
Then the website and API start in that chat's private Compose project
And another chat with the same repository uses a different Compose project
```

#### Scenario: Compose is not documented

```gherkin
Given a Development Chat checkout has runnable README commands but no documented Compose file
When that chat's preview starts
Then the documented commands run without generating a Compose file
```

#### Scenario: Unsafe Compose configuration is rejected

```gherkin
Given a documented Compose file requests host networking or a Docker socket mount
When that chat's preview starts
Then the unsafe preview configuration is rejected
And no host resource is exposed to the preview
```