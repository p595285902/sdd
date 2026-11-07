import { expect, test } from "@playwright/test"

import {
  applyStreamEvent,
  cacheConversation,
  emptyConversation,
  reconcileMessages,
  startAgentTurn,
  startOptimisticTurn,
} from "../src/features/develop/state"

test("bounds the conversation cache to five recently touched chats", () => {
  let cache = {}
  for (let index = 1; index <= 6; index += 1) {
    cache = cacheConversation(cache, `chat-${index}`, emptyConversation())
  }

  expect(Object.keys(cache)).toEqual([
    "chat-2",
    "chat-3",
    "chat-4",
    "chat-5",
    "chat-6",
  ])
})

test("keeps optimistic messages while running and reconciles after completion", () => {
  const optimistic = startOptimisticTurn(
    emptyConversation(),
    "chat-1",
    "Inspect the repository",
    1000,
  )
  const persisted = {
    id: "persisted-1",
    chat_id: "chat-1",
    role: "user" as const,
    content: "Earlier message",
    created_at: "2026-09-24T12:00:00Z",
  }

  expect(reconcileMessages(optimistic, [persisted]).messages).toHaveLength(2)
  expect(
    reconcileMessages(optimistic, [
      persisted,
      { ...persisted, id: "persisted-2", content: "Inspect the repository" },
    ]).messages,
  ).toHaveLength(2)
  expect(
    reconcileMessages({ ...optimistic, running: false }, [persisted]).messages,
  ).toEqual([persisted])
})

test("deduplicates replayed stream events by sequence", () => {
  const running = startOptimisticTurn(
    emptyConversation(),
    "chat-1",
    "Inspect",
    1000,
  )
  const first = applyStreamEvent(running, {
    sequence: 1,
    kind: "text",
    data: "Hello",
  })
  const replay = applyStreamEvent(first, {
    sequence: 1,
    kind: "text",
    data: "Hello",
  })

  expect(replay.response).toBe("Hello")
  expect(replay).toBe(first)
})

for (const workflow of ["Explore", "Propose", "Apply"]) {
  test(`${workflow} keeps a live partial response and retires it for its exact persisted result`, () => {
    const running = startAgentTurn(emptyConversation(), 1000)
    const partial = applyStreamEvent(running, { sequence: 1, kind: "text", data: "  **Ready** " })
    expect(partial.running).toBe(true)
    expect(partial.response).toBe("  **Ready** ")
    const message = {
      id: "assistant-result", chat_id: "chat-1", role: "assistant" as const,
      content: "**Ready** now", activity: [{ text: "Inspecting repository" }],
      duration_seconds: 2, created_at: "2026-09-24T12:00:00Z",
      kind: workflow === "Propose" ? "proposal" : "message",
      proposal_state: workflow === "Propose" ? "undecided" : null,
    }
    const result = applyStreamEvent(partial, { sequence: 2, kind: "result", data: JSON.stringify(message) })
    const completed = applyStreamEvent(result, { sequence: 3, kind: "done", data: message.content })
    expect(completed.running).toBe(false)
    expect(completed.response).toBe("")
    expect(completed.messages).toEqual([message])
    expect(reconcileMessages(completed, [message as typeof completed.messages[number]]).messages).toEqual([message])
  })
}

test("retires transient stream content after the assistant message persists", () => {
  const completed = {
    ...emptyConversation(),
    activity: ["Inspecting repository"],
    response: "Repository updated.",
    startedAt: 1000,
  }
  const persisted = {
    id: "assistant-1",
    chat_id: "chat-1",
    role: "assistant" as const,
    content: "Repository updated.",
    created_at: "2026-09-24T12:00:00Z",
  }

  expect(reconcileMessages(completed, [persisted])).toMatchObject({
    messages: [persisted],
    activity: [],
    response: "",
    startedAt: null,
  })
})
