# Custom openspec schema
- update config.yaml with the new schema name
- create schemas folder and add the new schema.
- things modified from the OpenSpec:
    - spec.md: Follows Given-When-Then
    - tasks.md:create acceptance tests before the code
- added 2 new skills
    - acceptance-test-authoring
    - bdd-zone-check: verified if the apporach is properly followed
- hook
    - zone-guard.sh: make sure commit cannot have both spec and code changes.

OpenCode automatically loads Claude configs (`CLAUDE.md`) if no `AGENTS.md` exists. Global/Project rules and uses skills under .claude folder
Details can be found here: https://opencode.ai/docs/rules/


## File/content sent to every LLM reqest:
- CLAUDE.md
- name and descriptions of SKILL.md

## Openspec propose sends the following files: (avg 5k-30k tokens, large projects: 50k-150k tokens)
- CLAUDE.md
- openspec-propse/SKILL.md
- openspec/config.yaml relevant fields only such as context, rules for proposal
- active schema `schemas/behavior-driven/schema.yaml`
- artifact templates for the schema
- artifact files (if they were dependencies). IE Tasks depends on design and spec
- relevant repo files
