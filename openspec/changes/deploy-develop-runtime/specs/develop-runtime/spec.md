# Develop runtime

Develop runtime packages and configures the operational dependencies required by the complete Develop workflow.

## ADDED Requirements

### Requirement: Production runtime provides Develop dependencies
The backend runtime SHALL provide compatible `git`, `opencode`, and `openspec` executables and SHALL persist Development Workspaces outside the application container lifecycle.

#### Scenario: Runtime contains required development tools

```gherkin
Given the production backend image is built
When its Develop tool versions are inspected
Then git is available
And opencode is available
And openspec is available
```

### Requirement: Production topology preserves process-local coordination
The initial production deployment MUST run one FastAPI worker and SHALL configure proxies to preserve unbuffered Agent Turn streams beyond the heartbeat interval.

#### Scenario: Backend starts with one worker

```gherkin
Given the production backend configuration is loaded
When the backend service starts
Then exactly one FastAPI worker is configured
```
