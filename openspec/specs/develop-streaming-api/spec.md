# Develop streaming API

## Purpose

Browser clients need bearer-authenticated live Agent Turn delivery and ordered replay without weakening Development Chat ownership isolation or losing idle connections.

## Requirements

### Requirement: Owners can stream and reattach to Agent Turns
The system SHALL expose bearer-authenticated streams for starting and reattaching to Agent Turns, SHALL emit heartbeats during idle periods, and MUST preserve ownership without disclosing missing or foreign chats.

#### Scenario: Owner reattaches through the stream API

```gherkin
Given an authenticated user's Development Chat has an active Agent Turn
When the user opens its reattachment stream
Then buffered events are delivered before new events
And the stream remains open through completion
```