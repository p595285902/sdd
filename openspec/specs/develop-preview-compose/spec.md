# Develop preview Compose

## Purpose
Run documented, existing multi-service Compose previews for each Development Chat while isolating its builds, services, resources and cleanup from the host and other chats.

## Requirements

### Requirement: Documented Compose workflows start per chat
The system SHALL use an existing Compose file only when the selected checkout's root README calls for it. A trusted adapter SHALL validate the resolved model and all required dependencies before building or starting any service. It SHALL start all services required by the website, including its API, under a private chat-unique project without public ports or host control access, and MUST NOT generate or change the checkout's Compose file.

#### Scenario: Website requires an API service

```gherkin
Given a Development Chat checkout has a README describing an existing Compose file with website and API services
When that chat's preview starts
Then the website and API start in that chat's private Compose project
And another chat with the same repository uses a different Compose project
```

#### Scenario: Compose dependencies communicate only within their chat

```gherkin
Given a Development Chat checkout has a documented Compose website that depends on an API
When the chat's private Compose project starts
Then the website can reach its API by service name within that chat's network
And neither service can reach the host, backend or another chat's private network
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

### Requirement: Compose build and service isolation are bounded
The trusted adapter SHALL use only validated checkout-local build inputs, permitted image sources and approved registry acquisition without general build or runtime egress. It SHALL apply non-root execution, dropped privileges, bounded CPU, memory, processes, writable storage and lifetime to every service, SHALL NOT forward backend secrets, and SHALL reject the entire project before creating resources if any required service or build needs unsupported options or host access. It SHALL remove only the owning chat's project resources on failure, restart, deletion or expiry.

#### Scenario: Unsafe dependency prevents the entire project from starting

```gherkin
Given a documented Compose website depends on a service with a host mount or public port
When that chat's preview starts
Then the whole Compose project is rejected before any service starts
And no host resource is exposed to the preview
```

#### Scenario: Unsupported build source is rejected

```gherkin
Given a documented Compose service requires a build source outside its checkout or unrestricted network access
When that chat's preview starts
Then the unsupported build is rejected before any service starts
And the user is asked for compatible instructions in that chat
```

#### Scenario: Removing one chat cleans up only its project

```gherkin
Given two Development Chats have separate running private Compose projects
When one chat's preview expires or is deleted
Then that chat's containers, network and writable storage are removed
And the other chat's services remain available
```