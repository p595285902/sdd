## 1. Command runners and event model

- [x] 1.1 Add normalized agent event and bounded activity-part models
- [x] 1.2 Implement shared secret scrubbing and validated `ses_...` session identifiers
- [x] 1.3 Implement the production runner with process groups, stderr draining, bounded waits, and termination escalation
- [x] 1.4 Add a narrow process fixture for blocking, failure, malformed output, cancellation, and termination-escalation tests
- [x] 1.5 Add representative OpenCode fixtures and focused parser, scrubber, and runner tests

## 2. Exploration service

- [x] 2.1 Port conversation summarization and `/openspec explore` prompting from AIDev
- [x] 2.2 Execute exploration only in the validated owning workspace with a minimal environment
- [x] 2.3 Persist the user message before execution and atomically persist scrubbed bounded completion data and session state
- [x] 2.4 Add service tests for workspace confinement, session continuation, unknown events, output bounds, cancellation, and failures

## 3. Acceptance infrastructure

- [x] 3.1 Implement a programmable local OpenAI-compatible fake LLM with an out-of-band test control API
- [x] 3.2 Run the production runner and real OpenCode against the fake LLM in acceptance tests, rejecting external provider endpoints

## 4. Acceptance scenarios — each task is red, then green, then committed

- [x] 4.1 User explores a ready repository — red -> green -> commit
- [x] 4.2 User updates a repository through OpenCode — red -> green -> commit
- [x] 4.3 OpenCode receives the provider credential — red -> green -> commit
- [x] 4.4 Agent output contains a configured secret — red -> green -> commit

## 5. Completion

- [x] 5.1 Run backend tests and static checks for the runner and agent service
- [x] 5.2 Confirm acceptance mode runs production OpenCode only against the local fake LLM
- [x] 5.3 Run spec lint and the full effective acceptance suite with zero pending or undefined steps
