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

Issues:
## changes done for acceptance tests should have exceptions
- because each change require a change spec this means same for acceptance tests changes
- this created unneccesaary tests 
- do we keep the flow and remove/skip the test related specs after?
- Do we need the spec to change test related code? If its a long task spec should be better as it helps to verify and make sure stuff are working as intended. So probably yes
- Okay then we add logic to skip them after the code change is done. Do it during openspec archving? Or just remove them ( skip looks bad)


lifecycle-validation
`After` hook
    - move all the cleanup related to `Before` hook


Not safely by simply deleting the current hook. It does useful work that reset does not replace:

- Prints application logs after failures.
- Waits for outstanding reset-test fixture work and cleans up fixture-owned resources.
- Stops tracked preview workloads.
- Closes browser contexts and disposes API contexts.
- Records the scenario’s completion.


A particularly important detail: Cucumber creates a fresh World for each scenario. The next scenario’s Before does not own the previous World’s API-context list, so its replaceContexts() is not a substitute for disposing the previous scenario’s clients.

Does `Before` needs to know the previous World's API-context list? It simply wipeout everything. Prove me wrong.


resetting the server does not dispose client resources running in the test process
- 

When cleanup silently leaves something behind
- in what cases it will do that? and how can you prevent it from happening so a success cleanup means everything is cleaned up


whole-reset overhead was 3m26s
reset checks takes around 25 secs total

Added:
    docs(openspec): scope acceptance-only archive guidance
        -archive without sync when doing changes for acceptance-only 
To add:
- a final cleanup after all the tests finishes