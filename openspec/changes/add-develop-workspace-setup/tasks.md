## 1. Workspace configuration and service

- [x] 1.1 Add repository URL, repository token, workspace root, setup timeout, and fake setup-runner settings with safe validation
- [x] 1.2 Add workspace readiness state and schema changes with a verified migration and focused model tests
- [x] 1.3 Implement direct-child path validation, idempotent cleanup, and clean retry behavior
- [x] 1.4 Implement credential-safe clone plus `opencode` and `openspec` initialization behind the setup runner
- [x] 1.5 Add service tests for isolation, partial setup, credential handling, traversal rejection, and cleanup failure

## 2. API and controls

- [x] 2.1 Add ownership-scoped repository setup and readiness endpoints with safe errors
- [x] 2.2 Extend confirmed chat deletion to remove the validated workspace before database state
- [x] 2.3 Add Set up repository and confirmed deletion controls to the minimal Develop interface
- [x] 2.4 Add focused API and frontend tests for setup state, retries, cancellation, and deletion

## 3. Acceptance scenarios — each task is red, then green, then committed

- [x] 3.1 User sets up the configured repository — red -> green -> commit
- [x] 3.2 Repository setup is unavailable when configuration is missing — red -> green -> commit
- [x] 3.3 Development Workspaces are isolated — red -> green -> commit
- [x] 3.4 User cancels Development Chat deletion — red -> green -> commit
- [x] 3.5 User confirms Development Chat deletion — red -> green -> commit

## 4. Completion

- [x] 4.1 Run backend tests and static checks for workspace lifecycle
- [x] 4.2 Run frontend checks and focused interaction tests
- [x] 4.3 Run spec lint and the full effective acceptance suite with zero pending or undefined steps

## 5. Demo repository setup

- [ ] 5.1 Add validated `DEMO_GITHUB_REPO` and `DEMO_GITHUB_TOKEN` settings without exposing either value
- [ ] 5.2 Add an ownership-scoped demo setup endpoint that reuses the credential-safe workspace service
- [ ] 5.3 Add Set up demo repository next to Set up repository and represent its availability independently
- [ ] 5.4 Add focused backend and frontend tests for demo setup success, missing configuration, and credential safety
- [ ] 5.5 User sets up the demo repository — red -> green -> commit
- [ ] 5.6 Demo repository setup is unavailable when configuration is missing — red -> green -> commit

## 6. Demo repository completion

- [ ] 6.1 Run backend tests and static checks for both repository setup paths
- [ ] 6.2 Run frontend checks and focused interaction tests for both setup controls
- [ ] 6.3 Run spec lint and the full effective acceptance suite with zero pending or undefined steps
