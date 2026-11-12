import { expect, test } from "@playwright/test"

import {
  emptyPreviewOutput,
  executionActive,
  mergePreviewEvents,
  type PreviewExecution,
  type PreviewExecutionEvent,
  previewEventText,
  previewTimeline,
  safePreviewText,
  streamPreviewExecution,
} from "../src/features/develop/previewExecution"

const execution: PreviewExecution = {
  id: "execution-one",
  chat_id: "chat-one",
  created_at: "2026-09-24T12:01:00Z",
  updated_at: "2026-09-24T12:01:00Z",
  status: "running",
  ready: true,
  workflow: "docker compose watch",
  last_sequence: 4,
  truncated_bytes: 0,
}
const event = (
  sequence: number,
  kind: PreviewExecutionEvent["kind"] = "stdout",
  payload: PreviewExecutionEvent["payload"] = { text: `${sequence}\n` },
): PreviewExecutionEvent => ({
  execution_id: execution.id,
  sequence,
  kind,
  payload,
  created_at: execution.created_at,
})

test("durable cursor deduplicates replay/live rows and isolates execution identity", () => {
  const initial = mergePreviewEvents(emptyPreviewOutput(), execution.id, [
    event(2),
    event(1),
    event(2),
  ])
  expect(initial.events.map(({ sequence }) => sequence)).toEqual([1, 2])
  const resumed = mergePreviewEvents(initial, execution.id, [
    event(2),
    event(3),
    { ...event(4), execution_id: "other" },
  ])
  expect(resumed.events.map(({ sequence }) => sequence)).toEqual([1, 2, 3])
  expect(resumed.lastSequence).toBe(3)
  expect(mergePreviewEvents(resumed, execution.id, [event(1)])).toBe(resumed)
  // Snapshot last_sequence describes server persistence, not the browser cursor.
  expect(initial.lastSequence).toBeLessThan(execution.last_sequence)
})

test("browser output bounds disclose omitted bytes and retain final command/status", () => {
  const output = mergePreviewEvents(
    emptyPreviewOutput(),
    execution.id,
    [
      event(1, "command_start", {
        argv: ["docker", "compose", "watch"],
        cwd: "/workspace",
      }),
      event(2, "stdout", { text: "old output" }),
      event(3, "stderr", { text: "new" }),
      event(4, "command_exit", { exit_code: 9 }),
      event(5, "status", { status: "failed", reason: "Startup failed" }),
    ],
    3,
  )
  expect(output.events.map(({ sequence }) => sequence)).toEqual([1, 3, 4, 5])
  expect(output.omittedBytes).toBe(10)
  expect(output.lastSequence).toBe(5)
  expect(previewEventText(output.events[2])).toContain("Command exited (9)")
  expect(previewEventText(output.events[3])).toContain("failed: Startup failed")
})

test("operations merge chronologically without becoming messages or completing ready watch sessions", () => {
  const messages = [
    { id: "later", created_at: "2026-09-24T12:02:00Z" },
    { id: "earlier", created_at: "2026-09-24T12:00:00Z" },
  ]
  expect(
    previewTimeline(messages, [execution]).map(({ kind, id }) => [kind, id]),
  ).toEqual([
    ["message", "earlier"],
    ["execution", execution.id],
    ["message", "later"],
  ])
  expect(messages).toHaveLength(2)
  expect(executionActive(execution)).toBe(true)
  for (const status of ["failed", "stopped", "interrupted"] as const) {
    expect(executionActive({ ...execution, status })).toBe(false)
  }
})

test("markup stays literal while terminal hyperlinks, clipboard, CSI, control and bidi instructions are stripped", () => {
  const markup = '<script>alert("x")</script>**not markdown**'
  expect(
    safePreviewText(
      `\u001b[31m${markup}\u001b[0m\u001b]52;c;secret\u0007\u001b]8;;https://hostile.test\u001b\\text\u001b]8;;\u001b\\\u001bPignored\u001b\\\u0000‮\n`,
    ),
  ).toBe(`${markup}text\n`)
  expect(safePreviewText("ok\u009d52;payload\u009c\u009b2Jnext")).toBe("oknext")
  expect(
    previewEventText(
      event(1, "command_start", {
        argv: ["docker", "compose", "watch"],
        cwd: "/workspace",
      }),
    ),
  ).toBe("[/workspace] $ docker compose watch\n")
  for (const kind of ["truncated", "output_truncated", "gap"] as const) {
    expect(previewEventText(event(2, kind, { truncated_bytes: 40 }))).toContain(
      "Output truncated: 40 bytes omitted",
    )
  }
  expect(
    previewEventText(
      event(3, "truncated", { dropped_bytes: 20, total_dropped_bytes: 80 }),
    ),
  ).toContain("80 bytes omitted")
  expect(previewEventText(event(4, "gap", { through_cursor: 200 }))).toContain(
    "through output cursor 200",
  )
})

test("preview output uses an independent header-authenticated SSE stream and handles split CRLF frames", async () => {
  let requested: { url: string; options?: RequestInit } | undefined
  const frame = `: keepalive\r\n\r\nevent: preview-event\r\ndata: ${JSON.stringify(event(3))}\r\n\r\nevent: unrelated\r\ndata: {}\r\n\r\n`
  const chunks = [frame.slice(0, 9), frame.slice(9, -1), frame.slice(-1)]
  const fakeFetch: typeof fetch = async (input, options) => {
    requested = { url: String(input), options }
    return new Response(
      new ReadableStream({
        start(controller) {
          for (const chunk of chunks)
            controller.enqueue(new TextEncoder().encode(chunk))
          controller.close()
        },
      }),
    )
  }
  const received = []
  for await (const item of streamPreviewExecution({
    url: "/preview/executions/execution-one/stream?after=2",
    token: "owner-token",
    signal: new AbortController().signal,
    fetch: fakeFetch,
  }))
    received.push(item)
  expect(received).toEqual([event(3)])
  expect(requested?.url).toContain("after=2")
  expect(new Headers(requested?.options?.headers).get("Authorization")).toBe(
    "Bearer owner-token",
  )
  expect(requested?.options?.method).toBeUndefined()
})

test("preview stream rejects denied owner access without displaying output", async () => {
  const denied: typeof fetch = async () =>
    new Response("Denied", { status: 403 })
  await expect(async () => {
    for await (const _event of streamPreviewExecution({
      url: "/preview/stream",
      token: "other",
      signal: new AbortController().signal,
      fetch: denied,
    })) {
      throw new Error("Output must not arrive")
    }
  }).rejects.toThrow("403")
})
