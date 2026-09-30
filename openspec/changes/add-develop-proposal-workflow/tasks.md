## 1. Proposal domain and agent operations

- [x] 1.1 Add proposal message kind and undecided, approved, and rejected state with a verified migration
- [x] 1.2 Port bounded canonical conversation summarization and `/openspec propose` execution
- [x] 1.3 Add `/openspec apply` execution confined to the validated owning workspace
- [x] 1.4 Add model and service tests for state transitions, session continuity, workspace confinement, and no remote publication

## 2. API and interface

- [x] 2.1 Add ownership-scoped proposal creation, approve, and reject endpoints
- [x] 2.2 Implement atomic first-decision-wins handling and exactly-once apply-turn startup
- [x] 2.3 Add API tests for repeated and conflicting decisions, failures, and weighted apply admission
- [x] 2.4 Add Make it happen, Approve, and Reject controls with persisted decision state
- [x] 2.5 Add frontend and Playwright tests for proposal loading, disabled decisions, approval streaming, and rejection

## 3. Acceptance scenarios — each task is red, then green, then committed

- [x] 3.1 User requests a proposal — red -> green -> commit
- [x] 3.2 User approves a proposal — red -> green -> commit
- [x] 3.3 User rejects a proposal — red -> green -> commit

## 4. Completion

- [x] 4.1 Run backend tests and static checks for proposal state and operations
- [x] 4.2 Run frontend checks and proposal workflow Playwright tests
- [x] 4.3 Run spec lint and the full effective acceptance suite with zero pending or undefined steps
