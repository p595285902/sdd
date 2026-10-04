# Develop preview instructions

## ADDED Requirements

### Requirement: Startup uses checkout instructions
The system SHALL pass the root README of the selected Development Chat's checkout to its agent and SHALL use documented commands and localhost service ports to start that chat's isolated preview without another approval prompt. It MUST NOT guess an undocumented command or pass application secrets into the preview.

#### Scenario: README documents a website and API startup

```gherkin
Given a Development Chat checkout has a root README documenting website and API startup commands
When startup instructions are resolved for that chat
Then the documented commands and localhost ports are selected for that chat
And no additional command approval is required
```

### Requirement: Missing instructions are requested in chat
The system MUST ask the user for startup commands or a pointer to instructions when the root README has none, and SHALL use the response for only that Development Chat once it is supplied.

#### Scenario: README has no startup instructions

```gherkin
Given a Development Chat checkout has no startup commands in its root README
When startup instructions are resolved for that chat
Then the user is asked in chat for a command or a pointer to instructions
And no undocumented command is executed
When the user provides startup instructions
Then those instructions are used only for that chat's preview
```