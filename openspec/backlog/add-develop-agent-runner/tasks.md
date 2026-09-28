## 1. Command runners and event model

- [ ] 1.1 Add normalized agent event and bounded activity-part models
- [ ] 1.2 Implement shared secret scrubbing and validated `ses_...` session identifiers
- [ ] 1.3 Implement the production runner with process groups, stderr draining, bounded waits, and termination escalation
- [ ] 1.4 Implement the deterministic fake runner with scripted events, blocking, failure, and cancellation controls
- [ ] 1.5 Add representative OpenCode fixtures and focused parser, scrubber, and runner tests

## 2. Exploration service

- [ ] 2.1 Port conversation summarization and `/openspec explore` prompting from AIDev
- [ ] 2.2 Execute exploration only in the validated owning workspace with a minimal environment
- [ ] 2.3 Persist the user message before execution and atomically persist scrubbed bounded completion data and session state
- [ ] 2.4 Add service tests for workspace confinement, session continuation, unknown events, output bounds, cancellation, and failures

## 3. Acceptance scenarios — each task is red, then green, then committed

- [ ] 3.1 User explores a ready repository — red -> green -> commit
- [ ] 3.2 Agent output contains a configured secret — red -> green -> commit

## 4. Completion

- [ ] 4.1 Run backend tests and static checks for the runner and agent service
- [ ] 4.2 Confirm acceptance mode cannot select the production runner
- [ ] 4.3 Run spec lint and the full effective acceptance suite with zero pending or undefined steps
