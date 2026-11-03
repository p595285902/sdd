## 1. Git observation and turn integration

- [ ] 1.1 Add bounded Git-based before/after observations in the Development Workspace, covering tracked changes, staged/dirty tracked files, untracked and Git-ignored relevant files, and checkout-owned symlinks without staging or committing.
- [ ] 1.2 Preserve application-owned preview ignore rules, workspace path validation, explicit Git failure handling, and resource limits; add focused service tests for changed, unchanged, dirty, untracked, ignored, and unavailable observations.
- [ ] 1.3 Use the Git observer at every Agent Turn preview-change call site; expose an acceptance-only signal after the initial observation completes so fixtures can edit the checkout without a fixed ten-second wait.
- [ ] 1.4 Replace fake `.git` marker directories in affected acceptance fixtures with local initialized Git checkouts and a baseline commit, without remote access.

## 2. Step definitions

Implement each new step through existing acceptance helpers and intent-level page or fixture methods; run its targeted scenario red for the right reason, then green. Reuse unchanged steps where possible.

- [ ] 2.1 Implement `Given an Agent Turn has recorded its initial Git state in a ready Development Workspace` with observation-ready synchronization.
- [ ] 2.2 Implement `Given a ready Development Workspace has a dirty checkout and an Agent Turn with its initial Git state recorded` using a pre-existing tracked edit.
- [ ] 2.3 Implement `Given a Development Workspace has an untracked website source file and an Agent Turn with its initial Git state recorded`.
- [ ] 2.4 Implement `When the turn completes after editing that untracked file again` and assert the resulting preview-change event.
- [ ] 2.5 Implement `Given a Development Workspace ignores a website source file through its Git configuration` without altering application-owned ignore rules.
- [ ] 2.6 Implement `And an Agent Turn has recorded its initial Git state` for the checkout-ignored source scenario.
- [ ] 2.7 Implement `When the turn completes after changing that website source file` and verify the source change is reported.
- [ ] 2.8 Implement `When the turn completes after Git observation becomes unavailable` and verify no false event is emitted.

## 3. Completion

- [ ] 3.1 Extract and lint the effective specs; dry-run the effective suite to verify the modified requirement replaces the source requirement exactly once, with no archived scenarios.
- [ ] 3.2 Run focused backend observer and lifecycle tests, then the full effective acceptance suite with zero failed, pending, or undefined steps and an HTML report. Verify ignored paths, preview startup, cleanup, and absence of fixed ten-second preview-change fixture waits.