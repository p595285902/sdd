## Context

The acceptance runner starts one isolated Compose project per invocation and stops chat-owned previews after each scenario. The preview controller already returns a running preview for the same chat. A new chat gets a new container; Compose previews additionally stage build inputs, may download dependencies in a bounded helper, and build chat-labeled images with Docker build caching disabled. The historical effective-suite result is 496.90 seconds, but it does not identify preview cost. Two attempted fresh baseline runs stopped before scenarios because Docker Hub timed out resolving the backend's `python:3.14` image.

## Goals / Non-Goals

**Goals:**

- Reduce effective full-suite elapsed time when identical preview preparation occurs repeatedly.
- Keep each chat's checkout, processes, container labels, credentials, networks, and cleanup isolated.
- Observe preparation hits, misses, builds, container creations, and elapsed time so a speed claim is testable.

**Non-Goals:**

- Restore a live container or transfer an active workload to another chat.
- Keep preview state, build artifacts, or an acceptance stack warm between suite invocations.
- Change production preview API or bypass validation of build inputs.

## Decisions

1. **Measure before choosing the cacheable operation.** Record per-run counts and elapsed time for dependency preparation, image build, and workload create/start, plus full effective-suite wall time. The shared `preview-controller` is not the repeated workload; do not optimize its startup speculatively. Compare against the README's historical 496.90-second effective run only as context, not a controlled benchmark. If preparation is not a material cost, do not introduce a cache just to improve container counts.

2. **Reuse preparation, never a live workload.** Start by removing redundant work in acceptance fixtures where possible. If measured repetition occurs inside the controller, enable a narrowly scoped acceptance-only preparation cache through the acceptance Compose configuration; the default production path continues to prepare and validate normally. Keep per-chat containers, private sockets/networks, labels, image ownership, restart semantics, idle expiration, and scenario cleanup unchanged. A live-container snapshot/reset would have to prove that every process, tmpfs file, checkout mount, service container, and network is scrubbed, and is rejected.

3. **Key by complete, validated inputs.** Run the existing checkout validation and staging on every request. For dependency archives, key a bounded in-memory entry on the staged dependency context bytes, dependency kind, relevant Dockerfile/build options, approved base/runtime image identity and other inputs affecting output. Cache only a successfully validated complete artifact; a miss, changed input, or failed preparation must perform normal preparation or fail explicitly. Never key by chat ID, fixture label, or service name alone. An unchanged full build context may reuse run-local preparation; a source edit, dependency/lockfile edit, Dockerfile edit, or runtime change must miss. Preserve the existing resource limits and reject unsafe inputs before lookup.

4. **Keep the cache local to the acceptance project.** Store entries in the controller's process lifetime, with explicit byte/count limits; a new Compose project gets an empty cache. Any optional Docker build-layer reuse must build the first occurrence of an input afresh in that run, preserve each chat's labeled final image, and clean up project-owned artifacts. Docker's global base-image cache is not a substitute for the run-scoped prepared-input cache. Do not retain helper containers, volumes, or a cache directory across runs.

5. **Demonstrate the boundary in executable scenarios.** Extend the acceptance-stack-reuse page/fixture flow to create two independent chats with identical prepared inputs, then a changed-input case and a separate-run case. Assert preparation counts or equivalent controller diagnostics, distinct chat-owned running workloads, and unchanged cleanup/isolation; do not infer cache hits solely from elapsed time. Keep step definitions intent-level and Docker inspection in page objects.

## Risks / Trade-offs

- **A faster build is not necessarily a faster suite** -> Compare full effective-suite elapsed time and report counts separately; do not claim a causal speedup from the historical run alone.
- **Stale or unsafe artifact reuse** -> Revalidate and stage each checkout, hash all effective inputs, preserve validation and resource limits, and fail explicitly on cache corruption.
- **Cache growth or data crossing chats** -> Bound entries and bytes; share only validated immutable inputs, never a running container, private network, or mutable workspace.
- **Docker may reuse layers across projects or ignore cache hints** -> Keep run-local bookkeeping and verify first build and per-chat labels; disable optional build-layer reuse if it cannot meet the run boundary.
- **Registry outages prevent measurement** -> Report the environmental blocker, retry when available, and do not record a passed benchmark from a run with zero scenarios.

## Migration Plan

Add instrumentation and acceptance scenarios first, then implement the smallest measured preparation reuse behind an acceptance-only switch if the harness alone cannot remove the repeated work. Run focused controller/runner tests and the effective acceptance suite after code changes. Reverting the switch and cache logic returns to the current behavior without data migration; suite teardown must still remove only its own project resources.

## Open Questions

The proportion of current wall time spent in dependency setup versus image builds versus workload startup is not yet measured. Use the instrumented run to decide which preparation path warrants caching and whether the optimized effective suite is actually faster on this host.
