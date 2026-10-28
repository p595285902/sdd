# Acceptance stack reuse

## ADDED Requirements

### Requirement: Identical preview preparation is reusable within an acceptance run
The acceptance runner SHALL reuse completed, verified preview preparation for equivalent inputs within the same run, while each Development Chat MUST receive its own fresh preview workload and private resources.

#### Scenario: Equivalent checkouts preview independently

```gherkin
Given an acceptance run has prepared a preview for a Development Chat
When a different Development Chat starts a preview with identical preparation inputs
Then the second preview reuses the prepared inputs without repeating their preparation
And each chat has a distinct running preview workload using only its own checkout
```

### Requirement: Changed preview inputs cannot use stale preparation
The acceptance runner MUST prepare new inputs when any relevant preview source, dependency, build instruction, or runtime configuration changes, and MUST NOT reuse preparation from another acceptance run.

#### Scenario: Changed dependencies require new preparation

```gherkin
Given an acceptance run has prepared preview inputs for a Development Chat
When another chat starts a preview with changed dependency inputs
Then the changed inputs are prepared afresh
And the second chat receives a preview of its changed checkout
```

#### Scenario: Changed source requires new preparation

```gherkin
Given an acceptance run has prepared preview inputs for a Development Chat
When another chat starts a preview with changed source or build instructions
Then the changed inputs are prepared afresh
And the second chat receives a preview of its changed checkout
```

#### Scenario: A new run does not inherit prepared preview inputs

```gherkin
Given an acceptance run has prepared preview inputs
When a separate acceptance run starts a preview with identical inputs
Then the separate run does not inherit the first run's prepared preview inputs
And the first run's preview workloads and private resources remain unavailable to the separate run
```
