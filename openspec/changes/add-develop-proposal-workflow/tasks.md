## 1. Proposal domain and agent operations

- [ ] 1.1 Add proposal message kind and undecided, approved, and rejected state with a verified migration
- [ ] 1.2 Port bounded canonical conversation summarization and `/openspec propose` execution
- [ ] 1.3 Add `/openspec apply` execution confined to the validated owning workspace
- [ ] 1.4 Add model and service tests for state transitions, session continuity, workspace confinement, and no remote publication

## 2. API and interface

- [ ] 2.1 Add ownership-scoped proposal creation, approve, and reject endpoints
- [ ] 2.2 Implement atomic first-decision-wins handling and exactly-once apply-turn startup
- [ ] 2.3 Add API tests for repeated and conflicting decisions, failures, and weighted apply admission
- [ ] 2.4 Add Make it happen, Approve, and Reject controls with persisted decision state
- [ ] 2.5 Add frontend and Playwright tests for proposal loading, disabled decisions, approval streaming, and rejection

## 3. Acceptance scenarios — each task is red, then green, then committed

- [ ] 3.1 User requests a proposal — red -> green -> commit
- [ ] 3.2 User approves a proposal — red -> green -> commit
- [ ] 3.3 User rejects a proposal — red -> green -> commit

## 4. Completion

- [ ] 4.1 Run backend tests and static checks for proposal state and operations
- [ ] 4.2 Run frontend checks and proposal workflow Playwright tests
- [ ] 4.3 Run spec lint and the full effective acceptance suite with zero pending or undefined steps
