# Project

## Rules (non-negotiable)

### Rule 1 — Acceptance tests must always pass

- Run the acceptance suite after every code change, before considering the change complete.
- Every code change must be driven by an active spec change (a delta under `openspec/changes/`). Code written without one is invalid, even if the suite is green.
- If any acceptance test fails, the remedy depends on how the code came to exist:
  - Code driven by an active spec change: fix the code until the suite is green. Never leave it red.
  - Code written without a driving spec change: do not patch it. Revert all code changes (`git restore .` plus `git clean -fd` for untracked files, or drop the stash) and start over from the spec — create or update the spec delta first, then re-implement.

### Rule 2 — Specs and code are never modified together

- A task touches either `openspec/` (specs) or the rest of the repo (code) — never both.
- When updating specs: modify only files under `openspec/`.
- When writing code: do not touch anything under `openspec/`.
- Exception: any `tasks.md` file may be updated in either kind of task.
- The active zone is defined by pending git changes (staged, unstaged, or untracked): uncommitted code changes block spec edits and vice versa. Committing (or stashing) the pending work releases the zone — no new session needed.
- Enforced live: the PreToolUse hook `.claude/hooks/zone-guard.sh` (wired in `.claude/settings.json`) denies cross-zone edits based on `git status`. Never commit `openspec/` and code files together — commit each zone separately.
- If you hit a block, finish and commit the current zone's task first, then start the other zone's edits. See the `bdd-zone-check` skill for the full playbook.