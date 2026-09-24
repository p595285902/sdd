## 1. Streaming contract

- [ ] 1.1 Add SSE serialization for `session`, `status`, `text`, `error`, `idle`, and `done` events
- [ ] 1.2 Add bearer-authenticated start and reattachment streams backed by TurnSession subscriptions
- [ ] 1.3 Add heartbeat scheduling, no-cache headers, proxy-buffering protection, and disconnect cleanup
- [ ] 1.4 Add ownership-scoped Presence Mode and explicit stop JSON endpoints

## 2. Contract validation

- [ ] 2.1 Add API tests for authentication, indistinguishable not-found responses, SSE headers, event ordering, replay-before-live, heartbeat, and disconnect cleanup
- [ ] 2.2 Regenerate the frontend client and verify all Develop JSON controls are typed
- [ ] 2.3 Add the isolated bearer-authenticated fetch/SSE parser with malformed-frame and cancellation tests

## 3. Acceptance scenario — red, then green, then committed

- [ ] 3.1 Owner reattaches through the stream API — red -> green -> commit

## 4. Completion

- [ ] 4.1 Run backend API tests, frontend adapter tests, generated-client checks, and static checks
- [ ] 4.2 Run spec lint and the full effective acceptance suite with zero pending or undefined steps
