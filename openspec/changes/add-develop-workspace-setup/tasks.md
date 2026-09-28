## 1. Workspace configuration and service

- [ ] 1.1 Add repository URL, repository token, workspace root, setup timeout, and fake setup-runner settings with safe validation
- [ ] 1.2 Add workspace readiness state and schema changes with a verified migration and focused model tests
- [ ] 1.3 Implement direct-child path validation, idempotent cleanup, and clean retry behavior
- [ ] 1.4 Implement credential-safe clone plus `opencode` and `openspec` initialization behind the setup runner
- [ ] 1.5 Add service tests for isolation, partial setup, credential handling, traversal rejection, and cleanup failure

## 2. API and controls

- [ ] 2.1 Add ownership-scoped repository setup and readiness endpoints with safe errors
- [ ] 2.2 Extend confirmed chat deletion to remove the validated workspace before database state
- [ ] 2.3 Add Set up repository and confirmed deletion controls to the minimal Develop interface
- [ ] 2.4 Add focused API and frontend tests for setup state, retries, cancellation, and deletion

## 3. Acceptance scenarios — each task is red, then green, then committed

- [ ] 3.1 User sets up the configured repository — red -> green -> commit
- [ ] 3.2 Repository setup is unavailable when configuration is missing — red -> green -> commit
- [ ] 3.3 Development Workspaces are isolated — red -> green -> commit
- [ ] 3.4 User cancels Development Chat deletion — red -> green -> commit
- [ ] 3.5 User confirms Development Chat deletion — red -> green -> commit

## 4. Completion

- [ ] 4.1 Run backend tests and static checks for workspace lifecycle
- [ ] 4.2 Run frontend checks and focused interaction tests
- [ ] 4.3 Run spec lint and the full effective acceptance suite with zero pending or undefined steps
