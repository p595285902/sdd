## Context

Each Development Workspace is a Git checkout. Today `snapshot_workspace` reads and hashes every non-excluded file around an Agent Turn, and `relevant_turn_change` compares snapshots. The same bounded observation is used by exploration and proposal flows. The preview-detection requirement includes a second edit to an already-dirty file, untracked source, and an application-controlled ignore list; `git status` alone cannot distinguish the second edit from the first. The acceptance fixture currently sleeps for ten seconds to leave time for the edit, without knowing when the initial observation finished.

## Goals / Non-Goals

**Goals:**

- Use Git commands to observe the checkout before and after each turn, without committing, staging, or modifying its index.
- Preserve change detection for tracked, dirty, untracked, and checkout-ignored source files while excluding the fixed application-controlled paths.
- Bound work and fail closed when Git cannot provide a complete observation; let acceptance tests wait for the real observation boundary.

**Non-Goals:**

- Use the current dirty/clean status alone, rewrite user Git history, or change the preview event/API contract.
- Make the checkout's `.gitignore` an authority over the application's preview-ignore rules.
- Change production Agent Turn timing merely to accelerate tests.

## Decisions

1. **Compare Git observations across the turn, not against `HEAD` alone.** Capture bounded `git diff HEAD` output (with external diff and text conversion disabled) before and after the turn for tracked content and index changes. Comparing those two results distinguishes a new edit to a file already modified before the turn. A one-time `git status --porcelain` or a single post-turn diff would miss that case. The workspace must be verified as the expected repository; an unborn or unavailable `HEAD` fails closed rather than silently treating every path as changed.
2. **Include untracked content independently.** Enumerate paths using NUL-delimited `git ls-files --others` without `--exclude-standard`, then obtain bounded Git blob identities for relevant regular files and link targets using Git commands without writing objects to the checkout or following links outside it. Compare path/type/content identities before and after. Ordinary `git diff` omits untracked files, and `--exclude-standard` would omit relevant source hidden by checkout ignore rules. Filter paths through the existing application-owned `preview-ignore.txt`, never a checkout-provided override.
3. **Keep the observation atomic at the turn boundary.** Start observing before agent execution, signal completion of the initial observation to acceptance-only test code, then observe again only on completed turns and emit `preview-change` when relevant observations differ. The test synchronizes on this boundary before editing, rather than relying on a ten-second provider delay. Do not expose a production API change for this test signal.
4. **Preserve failure and resource semantics.** Apply bounded runtime, output size, and relevant-file limits comparable to today's detector; run Git without a shell and with explicit checkout cwd and argument separators. Treat nonzero exits, unsafe paths, limits, and incomplete output as unavailable, not as evidence of change. Keep the existing behavior for cancellation, failed turns, ignored paths, and preview startup.

## Risks / Trade-offs

- Git diffs can be large or invoke repository configuration -> Disable external diff/text conversion, bound output and runtime, and fail closed if Git cannot complete safely.
- Untracked and Git-ignored files require content observation beyond `git diff` -> Bound their enumeration and hashing; include symlink targets without dereferencing links outside the checkout.
- A check of active-turn status can precede the initial Git observation -> Use an acceptance-only observation-ready signal, and test that an edit made after the signal reaches the post-turn comparison.
- Existing acceptance workspaces use a fake clone that creates `.git` markers without a real commit -> Give relevant fixtures real, local initialized Git checkouts without reaching a remote or changing production setup.

## Migration Plan

Add Git-specific service tests and acceptance coverage first. Replace the detector at all Agent Turn call sites, verify the existing effective-suite scenarios and new cases, and keep the acceptance suite green. The change needs no stored-data migration; rollback restores the old observer and test fixtures.

## Open Questions

None for the spec: implementation may choose the least expensive Git commands that satisfy the bounded before/after contract.