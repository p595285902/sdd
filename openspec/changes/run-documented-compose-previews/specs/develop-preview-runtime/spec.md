# Develop preview runtime

## ADDED Requirements

### Requirement: Native Compose has a dedicated Docker environment per chat
The system SHALL give each native Compose workload its own containerized Docker daemon, filesystem, networks and writable storage; a distinct Compose project on the platform's shared daemon is not sufficient. Project Docker commands SHALL address only that private daemon. The workload MUST NOT receive platform/backend credentials, platform Docker configuration/control sockets, privileged platform host access, host-wide filesystem mounts, public platform service ports or access to another chat's checkout. Documented project-local environment files and ports bound only inside the sandbox SHALL be permitted. Platform-side workspace synchronization and authenticated application forwarding SHALL expose only the owning chat's selected checkout and application traffic, not a general route back into the platform. This contract provides container-level separation and MUST NOT be presented as VM-grade containment of hostile code.

#### Scenario: Project ports and names are local to the sandbox

```gherkin
Given two Development Chats document the same fixed container names and published application ports
When both native Compose workflows are explicitly launched
Then both applications can run without name or port collisions
And neither project's published ports are directly exposed on the platform host
```

#### Scenario: Platform Docker environment cannot redirect project commands

```gherkin
Given the platform process has Docker connection settings and private environment credentials
When a Development Chat's native Compose command executes
Then Docker connection settings select only that chat's private daemon
And platform Docker configuration and credentials are absent from its execution environment
```

#### Scenario: A sandbox cannot be provisioned safely

```gherkin
Given the deployment cannot provide the required private Docker sandbox without platform host privileges
When the user launches a preview
Then launch fails with an actionable diagnostic retained in the chat
And execution does not fall back to the platform's shared Docker daemon
```

### Requirement: Sandbox cleanup preserves durable launch history
The system SHALL preserve the existing five-minute timeout based only on visible Context activity and SHALL remove the owning chat's private daemon, command sessions, nested runtime resources and writable storage on failure, restart, expiry or deletion. Container logs and a connected chat output stream MUST NOT count as visible Context activity. Idle cleanup and application restart SHALL retain the chat's persisted redacted execution history; deleting the chat SHALL remove its launch records and streams under the same ownership boundary. Durable execution state SHALL reconcile with missing runtime resources after platform/controller restart so orphaned runs cannot remain falsely active or silently restart.

#### Scenario: Idle cleanup retains chat output

```gherkin
Given a Development Chat has a running Compose preview and persisted launch output
When five minutes pass without visible Context activity
Then its sandbox and command sessions are stopped and removed
And its chat retains the redacted commands, output and stopped status
```

#### Scenario: Output alone does not extend the idle lifetime

```gherkin
Given a Development Chat has a running preview with no visible Context activity
When its watch command continues emitting output for five minutes
Then the output does not keep the preview workload alive
And the chat retains the final stopped status
```

#### Scenario: Controller restart reconciles a missing sandbox

```gherkin
Given a persisted preview execution is active but its sandbox no longer exists after controller restart
When execution status is reconciled
Then the chat shows a terminal interrupted status for that execution
And no replacement sandbox starts without an explicit user action
```
