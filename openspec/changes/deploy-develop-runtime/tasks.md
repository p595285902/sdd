## 1. Runtime image and storage

- [ ] 1.1 Select and document compatible pinned versions of `opencode` and `openspec`
- [ ] 1.2 Install and verify `git`, `opencode`, and `openspec` in the backend runtime image without embedding credentials
- [ ] 1.3 Add persistent Development Workspace volume configuration and environment settings
- [ ] 1.4 Add image and Compose checks for executable versions, writable storage, and persistence across replacement

## 2. Topology and configuration safety

- [ ] 2.1 Change the initial backend runtime to exactly one FastAPI worker
- [ ] 2.2 Add startup validation for incomplete production Develop configuration and accidental real-runner acceptance configuration
- [ ] 2.3 Document process-local coordination, workspace storage, secret injection, SSE buffering, heartbeat, and proxy timeout requirements
- [ ] 2.4 Add focused startup and deployment-configuration tests

## 3. Acceptance scenarios — each task is red, then green, then committed

- [ ] 3.1 Runtime contains required development tools — red -> green -> commit
- [ ] 3.2 Backend starts with one worker — red -> green -> commit

## 4. Completion

- [ ] 4.1 Build the production image and verify all required executables
- [ ] 4.2 Run backend, frontend, Playwright, spec-lint, and full effective acceptance suites
- [ ] 4.3 Confirm no runtime dependency on the local AIDev checkout and no committed credentials
