---
name: acceptance-test-authoring
description: How to set up and write acceptance tests for this project — specs are Markdown (spec.md) whose headings carry the structure and whose fenced Gherkin carries the steps, extracted to .feature files at test time; runner configuration for either supported stack (JavaScript/cucumber-js or Python/behave) covering extraction, effective-spec composition of source-of-truth and active delta specs, archive exclusion, and the HTML report; spec linting over the extracted output; Page Object Model conventions for step definitions. Use when creating or modifying anything under acceptance-tests/, configuring the cucumber-js or behave runner, writing or refactoring step definitions, linting specs, choosing or reading the project's acceptance stack, or implementing tasks from an OpenSpec change that involve acceptance tests.
---

# Acceptance Test Authoring

The acceptance suite executes the Gherkin specs that live under `openspec/` against the running application. Specs are **Markdown files** (`spec.md`) in standard OpenSpec shape: the **structure** (capability, requirements, scenarios) is ordinary Markdown headings, and only the **Given/When/Then steps** sit inside fenced code blocks. The runner **extracts** them into real `.feature` files on every run, synthesizing `Feature:`/`Rule:`/`Scenario:` from the headings. Three sets of rules govern the suite: **spec format and extraction** (how Gherkin gets out of the Markdown), **runner invariants** (what the suite runs and how), and **code organization** (Page Object Model).

Keeping the structure in headings is what makes a spec valid OpenSpec: `openspec validate` and `openspec archive` read the headings, and **anything inside a fence is invisible to them**. That is why no structure may live in a fence.

Everything in this file is stack-agnostic. The tool-specific half — filenames, dependencies, commands — lives in the stack packs.

## Choosing the stack

The project's acceptance stack is declared as `stack:` in `openspec/config.yaml`:

```yaml
schema: behavior-driven
stack: javascript      # javascript | python
```

Resolve it in this order:

1. `stack:` in `openspec/config.yaml`.
2. If absent and `acceptance-tests/` already exists, infer it from the contents (`cucumber.cjs` → javascript, `behave.ini` → python) and offer to record it.
3. Otherwise **ask**. Never guess silently, and never scaffold a runner without a recorded value.

`openspec/config.yaml` is in the **specs zone**, so adding `stack:` is a specs-zone edit that must be committed on its own, before any `acceptance-tests/` scaffolding begins. See the `bdd-zone-check` skill.

## Reference files — pick your stack

| Stack | Pack | Runner |
|---|---|---|
| `javascript` | [references/javascript/SETUP.md](references/javascript/SETUP.md) | cucumber-js |
| `python` | [references/python/SETUP.md](references/python/SETUP.md) | behave 1.2.7+ |

Each pack has a **Files to copy** table naming every destination filename and why it is load-bearing, plus that stack's dependencies, commands, verification steps and Page Object Model example. Copy the files verbatim — they are the canonical runner.

Three files sit at the `references/` root because they are **shared by both stacks**:

| File | Role |
|---|---|
| [EXTRACTION.md](references/EXTRACTION.md) | Normative contract for `spec.md` → `.feature` |
| [COMPOSITION.md](references/COMPOSITION.md) | Normative contract for which scenarios actually run |
| [gherkin-lintrc.json](references/gherkin-lintrc.json) | Copied to `acceptance-tests/.gherkin-lintrc` by both stacks — spec linting is shared, so both accept and reject exactly the same specs |

The two Markdown files are the definition; the stack packs are bindings of them. Change the doc first, then both implementations.

## Spec format

A spec is `openspec/specs/<capability>/spec.md` (source of truth) or `openspec/changes/<id>/specs/<capability>/spec.md` (delta). Structure comes from Markdown headings; fences hold steps only.

- `# <capability>` — the H1 title, **exactly one per file**. Becomes `Feature:`.
- `## ADDED|MODIFIED|REMOVED|RENAMED Requirements` — delta sections in a change's delta spec. In `openspec/specs/` these are instead `## Purpose` (≥50 characters) and `## Requirements`.
- `### Requirement: <name>` — becomes `Rule:`. The line beneath it is the normative description and must contain SHALL/MUST as **plain prose, never fenced** — OpenSpec cannot see fenced text.
- `#### Scenario: <name>` (or `#### Scenario Outline: <name>`) — becomes `Scenario:`. Each **must** be followed by a gherkin fence before the next heading.
- Fences open with ` ```gherkin ` at **column 0** (3+ backticks, info string exactly `gherkin`) and close with at least as many backticks at column 0.
- A fence holds **only steps** (Given/When/Then/And/But), plus `Examples:` tables and docstrings. `Feature:`, `Rule:`, `Scenario:`, `Scenario Outline:` and `Example:` inside a fence are a **hard error** — that is the old format.
- Feature-level `Background:` goes under a `## Background` section with its own fence.
- There are **no `# @openspec:` marker comments**. The delta operation is the `##` section heading, and it applies to **every** requirement under it.

### Extraction

Extraction turns each `spec.md` into `acceptance-tests/.extracted/<same-relative-path>/spec.feature`, synthesizing `Feature:`/`Rule:`/`Scenario:` from the headings and copying fenced step lines verbatim.

**[references/EXTRACTION.md](references/EXTRACTION.md) is the normative definition** — the full line-by-line mapping, fence mechanics, and the table of hard errors and edge cases. Read it before touching either extractor or porting to a new language; both shipped extractors are bindings of it.

The two things worth knowing without opening it:

- **Line fidelity.** Every input line maps to exactly one output line, so line N of the `.feature` is line N of the `.md`. Runner output and the HTML report show extracted paths — read `.extracted/X/spec.feature:N` as `openspec/X/spec.md:N`, always.
- **`.extracted/` is generated.** Gitignored, wiped and rebuilt on every run, never edited by hand.

## Runner invariants

1. `acceptance-tests/` is an **independent test project in the configured stack**, at the repo root. Its hooks boot the application before the suite and shut it down after — the suite must be runnable with a **single command**. The repo `.gitignore` covers `acceptance-tests/.extracted/` and `acceptance-tests/reports/`.
2. The default run executes the **effective spec**: every `openspec/specs/**/spec.md` (source of truth) with every **active** change's delta (`openspec/changes/*/specs/**/spec.md`) applied — i.e. exactly what the source of truth will become once those changes are synced/archived — extracted to `.extracted/` and composed there. Which version of each requirement runs is defined in [references/COMPOSITION.md](references/COMPOSITION.md).
3. Superseded rules (MODIFIED/REMOVED by an active delta) must **not reach the runner** and must **not be reported as skipped**. **Never edit or tag the spec files to skip them** — the source of truth stays pristine until sync — and never let them show up as skipped counts, which pollute the zero-pending completion signal: a superseded rule is replaced, not unfinished. The mechanism differs per stack (COMPOSITION.md, step 4); the observable contract does not. Every exclusion is announced via the composition report on stderr — an excluded scenario must never be silently absent from results or the HTML report.
4. **A green effective suite is the gate for sync/archive — and sync/archive must never change suite results.** At propose time the suite goes red on exactly the delta's new/changed scenarios (that red set is the implementation work list); at completion it is fully green; syncing and archiving then only collapse the composition back to the source of truth. Never sync or archive on red.
5. **Specs under `openspec/changes/archive/` must NEVER execute.** Archived changes are historical deltas already merged into `openspec/specs/`; running them re-executes stale duplicates. This is non-negotiable. The extractor already skips the archive (nothing under `changes/archive/` reaches `.extracted/`), and the composition filters it again — defense in depth.
6. Alongside the default run, provide a **source-of-truth-only regression run** that executes `openspec/specs/` as-is, freshly extracted by the same entry point.
7. Every test run generates an **HTML report** under `acceptance-tests/reports/`.
8. **Verify the composition** whenever the runner config, the extractor, or the `openspec/` tree changes: do a dry run and confirm `.extracted/` was rebuilt, no loaded scenario originates from `openspec/changes/archive/`, no scenario appears twice, and no scenario of a superseded source-of-truth rule is loaded. The per-stack commands are in the pack's SETUP.md.

## Effective-spec composition

**[references/COMPOSITION.md](references/COMPOSITION.md) is the normative definition** — the per-section operation table, the six-step procedure, the two sanctioned exclusion bindings and why they differ per runner, the composition report format, and the fail/warn conditions. Each stack pack ships a binding of it; neither implementation is the definition.

### Port parity

The two reference docs — [EXTRACTION.md](references/EXTRACTION.md) and [COMPOSITION.md](references/COMPOSITION.md) — are **the contract between the stacks**, and the definition any new-language port implements. Neither shipped implementation is the definition. A change to one implementation must be mirrored in the other, reflected in the relevant doc **first**, and re-verified — otherwise the two silently drift and the same specs start meaning different things.

The strongest check is a cross-stack dry run on the same `openspec/` tree: **the same scenario count and the same scenario names**. Run it first after touching either extractor or either composition module. The per-stack dry-run commands are in the packs.

## Linting specs

Spec linting is **shared across stacks**: gherkin-lint over the extracted output, with the one pinned `.gherkin-lintrc`. That is deliberate — a stack-native linter would accept a different set of specs, and specs are the thing both stacks are supposed to agree on.

- Extract first, then lint; pass `.extracted` as a **directory argument** — a quoted `'**'` glob silently matches nothing through the dot-directory.
- gherkin-lint has **no default rules**; it requires `.gherkin-lintrc`. The pinned off-rules are load-bearing: `no-multiple-empty-lines` and `new-line-at-eof` would flood on the extraction's blank-line padding, `indentation` fires because steps keep their authored column under a synthesized indented `Scenario:`, and the dupe-name rules fire on legitimate SOT/delta pairs (same Feature name; MODIFIED deltas copy scenario names). Without them, "fix all lint issues" is unsatisfiable.
- Reported line numbers are valid in the source `spec.md` files.
- Known limitation: gherkin-lint's AST rules do not descend into `Rule:` children, so e.g. `no-unnamed-scenarios` misses scenarios nested under a Rule. Line-based rules (trailing spaces, tags) and feature-level rules work fine.

Linting a spec **before** an `acceptance-tests/` project exists (e.g. from a specs-authoring session) — run the extractor straight from the skill references, then lint. With the JS extractor (no venv needed):

```sh
node .claude/skills/acceptance-test-authoring/references/javascript/extract-gherkin.cjs openspec acceptance-tests/.extracted \
  && npx gherkin-lint --config .claude/skills/acceptance-test-authoring/references/gherkin-lintrc.json acceptance-tests/.extracted
```

The Python extractor is a drop-in substitute (`python .claude/skills/acceptance-test-authoring/references/python/extract_gherkin.py openspec acceptance-tests/.extracted`) — both are dependency-free and produce byte-identical output. The output dir is gitignored; writing it via Bash does not violate the spec/code zone split, which guards file edits only.

## Page Object Model

Step definitions must read as intent; all knowledge of the UI lives in page objects.

- Page objects live under `acceptance-tests/`, **one per screen or flow** (e.g. a signup page, a login page, a dashboard page).
- A page object encapsulates **all UI identifiers**: routes/URLs, form field names, CSS selectors and element ids. Parse responses with the stack's HTML parser — **never with regexes over raw HTML**.
- Page objects expose **intent-level methods**, e.g. `open()`, `submit_signup(...)`, `error_message()`, `confirmation_link()`. They receive the World (or its HTTP client) and use it for requests.
- Step definitions contain **no selectors, no regexes, no URLs** — only page-object calls and assertions.
- The World stays a thin HTTP client (request/response state, redirect helper). It holds page-object instances; it does not parse pages itself.
- When the UI changes an identifier, exactly one page object should need editing.

The per-stack idioms and a worked example are in each pack's SETUP.md.

## Workflow cadence

Implement one pending step definition at a time: run the suite so the step **fails for the right reason** (red), implement until it **passes** (green), then **commit**. The effective suite's red scenarios at propose time are exactly the change's work list. Finish only when every scenario passes with zero pending/undefined steps and the HTML report is generated — then, and only then, sync and archive.
