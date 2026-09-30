import { expect, test } from "@playwright/test"

import { streamDevelopTurn } from "../src/features/develop/stream"

const responseFrom = (...chunks: string[]) =>
  new Response(
    new ReadableStream({
      start(controller) {
        const encoder = new TextEncoder()
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    }),
    { headers: { "Content-Type": "text/event-stream" } },
  )

test("parses split Develop events and sends bearer authentication", async () => {
  let requestInit: RequestInit | undefined
  const events = streamDevelopTurn({
    url: "https://example.test/stream",
    token: "test-token",
    fetch: async (_input, init) => {
      requestInit = init
      return responseFrom(
        'id: 1\nevent: status\ndata: {"sequence":1,',
        '"kind":"status","data":"working"}\n\n: heartbeat\n\n',
        'data: {"sequence":2,"kind":"done","data":"complete"}\n\n',
      )
    },
  })

  const received = []
  for await (const event of events) received.push(event)

  expect(new Headers(requestInit?.headers).get("Authorization")).toBe(
    "Bearer test-token",
  )
  expect(received).toEqual([
    { sequence: 1, kind: "status", data: "working" },
    { sequence: 2, kind: "done", data: "complete" },
  ])
})

test("rejects malformed and invalid Develop event frames", async () => {
  const malformed = streamDevelopTurn({
    url: "https://example.test/stream",
    token: "token",
    fetch: async () => responseFrom("data: {bad json}\n\n"),
  })
  await expect(malformed.next()).rejects.toThrow("Malformed Develop SSE data")

  const invalid = streamDevelopTurn({
    url: "https://example.test/stream",
    token: "token",
    fetch: async () => responseFrom('data: {"kind":"text"}\n\n'),
  })
  await expect(invalid.next()).rejects.toThrow("Invalid Develop SSE event")
})

test("cancels the response reader when aborted", async () => {
  let cancelled = false
  let markFetched: (() => void) | undefined
  const fetched = new Promise<void>((resolve) => {
    markFetched = resolve
  })
  const controller = new AbortController()
  const stream = streamDevelopTurn({
    url: "https://example.test/stream",
    token: "token",
    signal: controller.signal,
    fetch: async () => {
      markFetched?.()
      return new Response(
        new ReadableStream({
          cancel() {
            cancelled = true
          },
        }),
      )
    },
  })
  const pending = stream.next()

  await fetched
  controller.abort()
  await pending

  expect(cancelled).toBe(true)
})
