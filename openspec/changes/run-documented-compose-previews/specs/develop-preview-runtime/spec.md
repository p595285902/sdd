# Develop preview runtime

## REMOVED Requirements

### Requirement: Preview workloads are private to their Development Chat

Reason: The blanket no-privileged-host-access contract conflicts with the approved privileged outer-sandbox option and overstates containment for trusted privileged deployments.
Migration: Replace it with the chat-scoped provisioning contract below, retaining resource limits, owner-scoped checkouts, no platform socket/credential injection and no direct platform application ports while documenting the privilege risk.

## ADDED Requirements

### Requirement: Preview workloads use chat-scoped inputs and controls
The system SHALL run preview code in a resource-bounded workload owned by exactly one Development Chat and SHALL attach or synchronize only that chat's selected checkout. It MUST NOT inject backend credentials, a platform Docker control socket, platform host bind mounts or another chat's checkout, and MUST NOT publish application ports directly on the platform host. For native Compose, deployment configuration MAY explicitly permit a privileged outer sandbox for trusted projects on a dedicated Docker host or VM; the private daemon SHALL remain rootless. This exception SHALL apply only to provisioning the outer sandbox, not to project-requested host access or privileged inner services. Privileged mode weakens host isolation and MUST NOT be presented as a security boundary against malicious or compromised projects, VM-grade containment or secure isolation between mutually untrusted chats.

#### Scenario: Two chats preview the same repository independently

```gherkin
Given two Development Chats have separate checkouts of the same repository
When a preview workload starts for each chat
Then each workload uses only its own chat's checkout
And neither workload is mounted with the other chat's checkout
```

#### Scenario: Preview receives no platform credentials or control socket

```gherkin
Given a Development Chat has a ready checkout
When its preview workload starts
Then the workload has resource limits and no backend credentials
And it has no host control socket or publicly published service port
```

### Requirement: Native Compose has a dedicated Docker environment per chat
The system SHALL give each native Compose workload its own containerized rootless Docker daemon, filesystem, networks and writable storage; a distinct Compose project on the platform's shared daemon is not sufficient. Project Docker commands SHALL address only that private daemon. Provisioning MUST NOT inject platform/backend credentials, platform Docker configuration/control sockets, platform host bind mounts or another chat's checkout, and MUST NOT publish application ports directly on the platform host. Deployment configuration MAY explicitly permit a privileged outer sandbox for trusted workloads on a dedicated Docker host or VM; project documentation MUST NOT enable that mode or obtain additional platform access. The daemon SHALL still run as the rootless user, resource limits SHALL still apply to the aggregate outer workload, and project-requested privileged inner services, platform host mounts and control sockets MUST be rejected. Documented project-local environment files and ports bound only inside the sandbox SHALL be permitted. Platform-side workspace synchronization and authenticated application forwarding SHALL be limited to the owning chat's selected checkout and registered application traffic, not a general platform-network proxy. Privileged outer mode relaxes host protections and SHALL be documented as an accepted trusted-deployment risk, not protection against hostile projects or secure multi-tenancy.

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

#### Scenario: Deployment permits a privileged outer sandbox

```gherkin
Given a trusted deployment explicitly enables privileged outer preview sandboxes
When the owner launches a documented Compose preview
Then only that chat's outer sandbox is provisioned in privileged mode
And its private Docker daemon runs as the rootless user
And Docker connection settings select only that chat's private daemon
And no platform socket, host bind mount, platform credential or other checkout is injected
And aggregate sandbox resource limits remain configured
And no application ports are published on the platform host
```

#### Scenario: An approved sandbox cannot be provisioned

```gherkin
Given the deployment cannot provision a private Docker sandbox within its configured privilege policy
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
