# Develop preview Compose

## REMOVED Requirements

### Requirement: Compose build and service isolation are bounded

Reason: Per-service non-root execution and the old restricted service model conflict with native application images and sandbox-local Compose resources.
Migration: Apply aggregate limits and platform-boundary protections to the dedicated native Compose sandbox as defined below.

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
The system SHALL confine the native daemon, builds, application containers, networks, volumes and writable data to the owning chat's resource-bounded sandbox. Only checkout-local build/bind inputs and explicitly permitted public image, package and build sources SHALL be available; platform secrets, platform host paths/control sockets and other chats' resources MUST remain unreachable. Resource limits SHALL cover the whole sandbox and its nested processes, storage and lifetime, not only individual application containers. Native application images and their required users SHALL be supported without imposing the old Python/Node-only service whitelist; sandbox-boundary violations MUST still be rejected. Sandbox-local publication or storage MUST NOT be mistaken for publication or mounts on the platform host. Failure, restart, deletion or expiry SHALL remove only that chat's runtime resources while preserving durable launch history until chat deletion.

#### Scenario: Nested workloads cannot exceed their sandbox budget

```gherkin
Given a Development Chat has a running native Compose sandbox with configured resource limits
When its project creates additional services or build processes
Then those processes remain within the owning sandbox's aggregate resource limits
And no additional platform resources become accessible to the project
```
