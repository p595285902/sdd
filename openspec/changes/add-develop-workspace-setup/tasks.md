## 1. Workspace configuration and service

- [x] 1.1 Replace configured-repository settings with validated `DEMO_GITHUB_REPO` and `DEMO_GITHUB_TOKEN`, retaining workspace root, timeout, and fake-runner settings
- [x] 1.2 Add workspace readiness state and schema changes with a verified migration and focused model tests
- [x] 1.3 Implement direct-child path validation, idempotent cleanup, and clean retry behavior
- [x] 1.4 Implement credential-safe clone plus `opencode` and `openspec` initialization behind the setup runner
- [x] 1.5 Add service tests for isolation, partial setup, credential handling, traversal rejection, and cleanup failure

## 2. API and controls

- [x] 2.1 Make the ownership-scoped setup and readiness endpoints demo-only with safe errors
- [x] 2.2 Extend confirmed chat deletion to remove the validated workspace before database state
- [x] 2.3 Replace Set up repository with Set up demo repository in the minimal Develop interface
- [x] 2.4 Update focused API and frontend tests for demo setup state, retries, cancellation, and deletion

## 3. Acceptance scenarios — each task is red, then green, then committed

- [x] 3.1 User sets up the demo repository — red -> green -> commit
- [x] 3.2 Demo repository setup is unavailable when configuration is missing — red -> green -> commit
- [x] 3.3 Development Workspaces are isolated — red -> green -> commit
- [x] 3.4 User cancels Development Chat deletion — red -> green -> commit
- [x] 3.5 User confirms Development Chat deletion — red -> green -> commit

## 4. Completion

- [x] 4.1 Run backend tests and static checks for demo workspace lifecycle
- [x] 4.2 Run frontend checks and focused interaction tests for the demo setup control
- [x] 4.3 Run spec lint and the full effective acceptance suite with zero pending or undefined steps
