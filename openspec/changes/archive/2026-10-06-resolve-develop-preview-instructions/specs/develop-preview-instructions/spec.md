# Develop preview instructions

## ADDED Requirements

### Requirement: Startup uses checkout instructions
The system SHALL pass the root README of the selected Development Chat's checkout to its agent and SHALL resolve documented dependency setup and website/API startup commands, working directories and localhost ports for that chat. It SHALL execute supported instructions in that chat's private workload without another approval prompt and verify that the documented services respond on their selected ports inside the workload. It MUST NOT guess an undocumented command or pass application secrets into the preview.

#### Scenario: README documents a website and API startup

```gherkin
Given a Development Chat checkout has a root README documenting dependency setup and non-Compose website and API startup commands with distinct localhost ports
When startup instructions are resolved and executed for that chat
Then the documented dependencies are installed and both documented services respond on their selected localhost ports inside that chat's workload
And no additional command approval is required
```

### Requirement: Documented commands run with bounded dependencies and chat-local service access
The system SHALL provide a private workload image with a shell, Python and uv, and Node.js with npm and Bun so supported documented Python and JavaScript dependency and start commands can run. It SHALL permit dependency downloads only from explicitly allowed package registries, with no access to host, private-network or backend services, and SHALL allow website and API processes within the same chat workload to reach each other on localhost. It SHALL confine writable checkout build artifacts and installed dependencies to that chat's checkout, with bounded scratch space, and SHALL retain CPU, memory, process, startup-time and idle-lifetime limits. It MUST NOT publish host ports, mount a Docker socket, expose backend secrets or permit access to another chat's checkout; it SHALL stop and clean up child processes on failure, timeout, expiry or deletion.

#### Scenario: Website reaches its API without a host port

```gherkin
Given a Development Chat has documented non-Compose website and API commands that require local dependencies
When its dependency setup and both servers run in the private workload
Then the website can reach its API on localhost inside that workload
And neither service has a published host port or access to backend secrets
```

#### Scenario: Startup exceeds its bound

```gherkin
Given a Development Chat has documented startup commands that do not become ready before the configured timeout
When those commands run in its private workload
Then startup fails with a redacted diagnostic visible in that chat
And its startup processes are stopped without affecting another chat's workload
```

### Requirement: Missing instructions are requested in chat
The system MUST ask the user for startup commands or a pointer to instructions when the root README has none, and SHALL use the response for only that Development Chat once it is supplied. It SHALL also ask for supported alternatives when the documented instructions require facilities unavailable in the private workload; it MUST NOT execute unsupported instructions.

#### Scenario: README has no startup instructions

```gherkin
Given a Development Chat checkout has no startup commands in its root README
When startup instructions are resolved for that chat
Then the user is asked in chat for a command or a pointer to instructions
And no undocumented command is executed
When the user provides startup instructions
Then those instructions are used only for that chat's preview
```

#### Scenario: README requires unsupported Compose startup

```gherkin
Given a Development Chat checkout has a root README documenting only Docker Compose startup
When startup instructions are resolved for that chat
Then the user is asked in chat for non-Compose startup commands or a checkout-local pointer
And no Compose command is executed
```