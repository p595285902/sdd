## Why

The acceptance suite repeatedly recreates its backend container while scenarios run, even when the requested demo-repository configuration is already active. Those unnecessary recreations add work to a single full-suite run without resetting its database or development workspaces.

## What Changes

- Keep one acceptance Compose project per full-suite run, as today, but avoid recreating its backend when a scenario requests an unchanged demo-repository configuration.
- Recreate the backend when the effective configuration actually changes, and preserve the behavior of scenarios that depend on the configured or unconfigured repository.
- Preserve scenario isolation, default and CI teardown, and the fresh browser context per scenario. Measure full-suite time before and after the change without a fixed percentage gate.
- Do not retain a stack across separate runs or add general database, workspace, mail, or preview-store resets.

## Capabilities

### New Capabilities

- `acceptance-stack-reuse`: Reuse the running acceptance backend within a full-suite run when its requested configuration has not changed, while retaining correct configuration transitions and test isolation.

### Modified Capabilities

None.

## Impact

- Acceptance runner lifecycle, scenario fixtures, focused runner tests, and acceptance test documentation.
- No production application behavior or normal development Compose behavior changes.
