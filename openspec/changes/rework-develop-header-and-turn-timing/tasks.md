## 1. Spec handoff

- [x] 1.1 Review and commit this spec-zone change separately before editing code, as required by the repository zone guard.

## 2. Persist Agent Turn duration

- [x] 2.1 Add a nullable nonnegative duration field to Development Messages and an additive Alembic migration that leaves historical messages readable.
- [x] 2.2 Capture server-side turn elapsed time and store it with assistant messages from completed turns, including persisted interrupted or timed-out responses where available.
- [x] 2.3 Return the optional duration in message API responses, regenerate the TypeScript client, and cover persistence and legacy messages with backend tests.

## 3. Develop workspace controls

- [x] 3.1 Move repository setup/status into a red, yellow, or green chat-header icon with accessible status and hover tooltip; keep setup availability and failure behavior intact. Keyboard-focus tooltip waived by user on 2026-10-02.
- [x] 3.2 Put rename beside the chat title and a mode-selecting Presence Mode dropdown beside Delete, persisting changes using the existing mutation.
- [x] 3.3 Preserve the Context sidebar and mobile entry point with the agreed empty state, and wrap the header controls so all actions remain reachable on small screens.
- [x] 3.4 Display the live timer beside "Agent activity" and the stored final duration on persisted assistant messages, omitting it for legacy messages; cover the UI states with focused frontend tests.

## 4. Executable scenarios

- [x] 4.1 Implement the pending repository status and chat-header control steps using the Develop page object; verify the scenarios red then green.
- [x] 4.2 Implement the pending Presence Mode and small-screen Context steps using the Develop page object; verify the scenarios red then green.
- [x] 4.3 Implement the pending running and persisted activity-duration steps with API and UI fixtures; verify the scenarios red then green.
- [x] 4.4 Implement the pending legacy-message duration step; verify the scenario red then green.

## 5. Completion

- [x] 5.1 Run focused backend and frontend checks, lint the extracted Gherkin, and validate the OpenSpec change.
- [x] 5.2 Run the full acceptance suite after code changes; require all scenarios passing with zero pending/undefined steps and an HTML report.