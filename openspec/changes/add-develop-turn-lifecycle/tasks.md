## 1. Turn state and admission

- [ ] 1.1 Add Presence Mode persistence, timeout, grace, capacity, weight, and per-user background-limit settings
- [ ] 1.2 Port and test the weighted FIFO concurrency gate with cancellation-safe capacity release
- [ ] 1.3 Implement TurnSession buffering, subscriber tracking, terminal state, and bounded replay
- [ ] 1.4 Implement the process-local DevelopTurnManager with one active turn per chat

## 2. Lifecycle integration

- [ ] 2.1 Integrate agent execution, completion persistence, session updates, and terminal event emission
- [ ] 2.2 Implement explicit stop and timeout through one idempotent process-termination path
- [ ] 2.3 Implement presence grace scheduling, reattachment withdrawal, and background slot accounting
- [ ] 2.4 Stop and await active turns before confirmed chat and workspace deletion
- [ ] 2.5 Add focused concurrent tests for races, replay bounds, timers, admission fairness, cleanup, and deletion ordering

## 3. Acceptance scenarios — each task is red, then green, then committed

- [ ] 3.1 Concurrent turn for one chat is rejected — red -> green -> commit
- [ ] 3.2 User explicitly stops an Agent Turn — red -> green -> commit
- [ ] 3.3 Stop when I leave cancels after the grace period — red -> green -> commit
- [ ] 3.4 Reattachment within the grace period preserves the turn — red -> green -> commit
- [ ] 3.5 Continue in background survives disconnection — red -> green -> commit
- [ ] 3.6 Background turn limit is enforced per user — red -> green -> commit
- [ ] 3.7 Agent Turn waits for capacity — red -> green -> commit
- [ ] 3.8 Agent Turn times out — red -> green -> commit

## 4. Completion

- [ ] 4.1 Run backend tests and static checks with deterministic timer and concurrency coverage
- [ ] 4.2 Run spec lint and the full effective acceptance suite with zero pending or undefined steps
