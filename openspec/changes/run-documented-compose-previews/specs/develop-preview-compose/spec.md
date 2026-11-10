# Develop preview Compose

## REMOVED Requirements

### Requirement: Compose build and service isolation are bounded

Reason: Per-service non-root execution and the old restricted service model conflict with native application images and sandbox-local Compose resources.
Migration: Apply aggregate limits and platform-boundary protections to the dedicated native Compose sandbox as defined below.

## MODIFIED Requirements

### Requirement: Documented Compose workflows start per chat
The system SHALL use an existing Compose file only when the selected checkout's root README calls for it, including through checkout-local linked instructions. A trusted adapter SHALL validate the resolved model and all required dependencies before building or starting any service. It SHALL start all services required by the website, including its API, under a private chat-unique project without directly published platform ports or injected platform control sockets, and MUST NOT generate or change the checkout's Compose file. Services SHALL use their chat's private network and MUST NOT be attached to platform or other chats' private networks. The explicitly configured privileged outer-sandbox exception SHALL NOT authorize project-requested host networking, platform Docker socket mounts or privileged inner services. These attachment and preflight controls MUST NOT be presented as guaranteeing that hostile code cannot reach the host from a privileged outer sandbox.

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
And neither service is attached to the platform or another chat's private network
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
And requested host networking and Docker socket mounts are not provisioned
```

## ADDED Requirements

### Requirement: Native Compose executes documented initialization and startup
The system SHALL execute the checkout's documented Compose initialization and startup sequence using native Docker Compose inside the owning Development Chat's containerized sandbox. It SHALL preserve documented working directories, command order, file selection, default override merging, interpolation, and service/dependency selection, including commands that omit explicit service names. It SHALL support ordinary application configuration such as project-local environment files, named volumes, confined bind mounts, health checks, dependency conditions, labels, build/image declarations, and sandbox-local published ports without generating or changing checkout Compose files. One-off initialization SHALL complete successfully before dependent startup commands execute. A long-running `watch` or foreground `up` SHALL be supervised without waiting for it to exit before testing application readiness. Ambiguous workflows or options that violate the sandbox boundary MUST fail with an actionable diagnostic rather than guessed commands or partial success.

#### Scenario: Initialization precedes a long-running watch command

```gherkin
Given a Development Chat README documents a one-off Compose database initialization command followed by a Compose watch command
When the user launches the documented workflow
Then the initialization command completes successfully before the watch command starts
And application readiness can be reported while the watch command remains running
And both commands and their output are visible in that chat
```

#### Scenario: Native Compose resolves the project configuration

```gherkin
Given a documented Compose workflow uses default override files, a project environment file, named volumes and a health-checked database dependency
When the user launches the workflow without explicit service names
Then native Compose applies those files and dependency conditions inside the owning chat's sandbox
And sandbox-local published ports and fixed container names do not collide with another chat or the platform
And the checkout's Compose files remain unchanged
```

#### Scenario: Initialization failure prevents later startup

```gherkin
Given a documented Compose workflow has initialization followed by application startup
When the initialization command exits with a nonzero status
Then the application startup command is not executed
And the failed command and exit status remain visible in that chat
And partial runtime resources are cleaned up only for that chat
```

#### Scenario: Documented workflow produces a usable full-stack application

```gherkin
Given a Development Chat has a documented Compose application with a frontend, API, database and first-user initialization
When the user launches the documented workflow
Then the application becomes usable inside Context
When the user logs in with the initialized preview account and creates an item
Then the item is saved through the application's API and database
```

### Requirement: Native Compose resources are bounded by their sandbox
The system SHALL place the native daemon, builds, application containers, networks, volumes and writable data in the owning chat's resource-bounded sandbox. Build/bind inputs SHALL be limited to the selected checkout, and image, package and build acquisition SHALL use explicitly permitted public sources. Provisioning MUST NOT inject platform secrets, platform host bind mounts/control sockets or other chats' checkouts; project requests for those resources or privileged inner services MUST be rejected. An explicitly configured privileged outer sandbox SHALL be permitted only for trusted projects on a dedicated Docker host or VM, with its private daemon still running rootless; this exception MUST NOT be represented as making platform resources unreachable to malicious or compromised code. Resource limits SHALL cover the whole sandbox and its nested processes, storage and lifetime, not only individual application containers. Native application images and their required users SHALL be supported without imposing the old Python/Node-only service whitelist; project-requested violations of the configured sandbox policy MUST still be rejected. Sandbox-local publication or storage MUST NOT be mistaken for publication or mounts on the platform host. Failure, restart, deletion or expiry SHALL remove only that chat's runtime resources while preserving durable launch history until chat deletion.

#### Scenario: Nested workloads cannot exceed their sandbox budget

```gherkin
Given a Development Chat has a running native Compose sandbox with configured resource limits
When its project creates additional services or build processes
Then those processes remain within the owning sandbox's aggregate resource limits
And no platform secrets, host bind mounts or control sockets are injected into the sandbox
```
