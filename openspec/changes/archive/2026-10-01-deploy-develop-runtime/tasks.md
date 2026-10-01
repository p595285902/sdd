## 1. Runtime image and storage

- [x] 1.1 Select and document compatible pinned versions of `opencode` and `openspec`
- [x] 1.2 Install and verify `git`, `opencode`, and `openspec` in the backend runtime image without embedding credentials
- [x] 1.3 Add persistent Development Workspace volume configuration and environment settings
- [x] 1.4 Add image and Compose checks for executable versions, writable storage, and persistence across replacement

## 2. Topology and configuration safety

- [x] 2.1 Change the initial backend runtime to exactly one FastAPI worker
- [x] 2.2 Add startup validation for incomplete production Develop configuration and accidental real-runner acceptance configuration
- [x] 2.3 Document process-local coordination, workspace storage, secret injection, SSE buffering, heartbeat, and proxy timeout requirements
- [x] 2.4 Add focused startup and deployment-configuration tests

## 3. Acceptance scenarios — each task is red, then green, then committed

- [x] 3.1 Runtime contains required development tools — red -> green -> commit
- [x] 3.2 Backend starts with one worker — red -> green -> commit

## 4. Completion

- [x] 4.1 Build the production image and verify all required executables
- [x] 4.2 Run backend, frontend, Playwright, spec-lint, and full effective acceptance suites
- [x] 4.3 Confirm no runtime dependency on the local AIDev checkout and no committed credentials
