# Develop preview instructions

## REMOVED Requirements

### Requirement: Missing instructions are requested in chat

Reason: The old requirement includes blanket Compose rejection and automatic execution after clarification.
Migration: Retain chat-local clarification with actionable execution diagnostics and an explicit subsequent launch.

## ADDED Requirements

### Requirement: Compose startup plans follow checkout-local documentation
The system SHALL resolve startup instructions from the selected Development Chat checkout's root README and documentation reachable through checkout-local links. It SHALL distinguish documented full-stack Compose workflows from alternative host-local development instructions, retain source references, and resolve the documented ordered setup/start commands, working directories, configuration files and application entry point. Documentation traversal and resolved filesystem inputs MUST remain within the selected checkout with bounded document count, depth and size; external documentation links and escaping symlinks MUST NOT be followed automatically. Resolving instructions SHALL NOT start the project. Explicit execution SHALL require no additional approval, MUST NOT invent commands or modify project configuration, and SHALL verify the selected application's response inside the workload. Project-local configuration MAY contain project credentials, but platform credentials MUST NOT be inherited.

#### Scenario: README links to the full Docker workflow

```gherkin
Given a Development Chat README links to checkout-local development documentation containing Compose initialization and startup instructions
When the startup instructions are resolved for that chat
Then the ordered Compose commands are resolved with references to that documentation
And alternative host-local frontend and backend commands are not combined into the Compose workflow
And no command is executed during instruction discovery
```

#### Scenario: Linked documentation escapes the checkout

```gherkin
Given a Development Chat README links to an external document or a symlink outside its checkout
When startup instructions are resolved
Then the outside document is not read automatically
And an incomplete workflow produces an actionable diagnostic in that chat
And no undocumented command is executed
```

#### Scenario: Documented project environment configures the preview

```gherkin
Given a documented Compose workflow requires a checkout-local environment file with database and first-user settings
When the user launches that workflow
Then the sandbox uses the documented project configuration
And no platform environment values or Docker credentials are inherited
And known project secret values are masked before output is streamed or persisted
```

### Requirement: Incomplete startup instructions are resolved per chat
The system SHALL report missing, conflicting or unsupported startup instructions in the owning Development Chat with an actionable request for a command or checkout-local pointer. It SHALL use supplied clarification only for that chat, SHALL NOT invent commands, and SHALL NOT silently rewrite project files or substitute a different startup workflow. A clarification is not an approval prompt; once instructions are available, execution SHALL still require an explicit Launch or Restart action. Compose itself MUST NOT be treated as unsupported merely because initialization uses `run`, startup uses `watch`, or documented commands omit service names.

#### Scenario: README has no startup instructions

```gherkin
Given a Development Chat checkout has no startup commands in its README or linked checkout-local docs
When the user launches the preview
Then the user is asked in chat for a command or a checkout-local pointer
And no undocumented command is executed
When the user provides startup instructions
Then those instructions are saved only for that chat's preview
And the project remains stopped until the user launches it again
```

#### Scenario: README documents a supported Compose startup

```gherkin
Given a Development Chat README documents Compose initialization followed by Compose watch
When the user launches the preview
Then the native Compose workflow is executed in that chat's sandbox
And the user is not asked to provide non-Compose commands
```

#### Scenario: Documented Docker workflows conflict

```gherkin
Given a Development Chat's documentation contains conflicting full-stack Docker startup instructions with no documented selection
When the user launches the preview
Then the conflict and its source documents are identified in that chat
And no startup workflow is guessed or executed
```
