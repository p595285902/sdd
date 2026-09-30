export type DevelopStreamEventKind =
  | "session"
  | "status"
  | "text"
  | "error"
  | "idle"
  | "done"

export type DevelopStreamEvent = {
  sequence: number
  kind: DevelopStreamEventKind
  data: string
}

type StreamDevelopTurnOptions = {
  url: string
  token: string
  method?: "GET" | "POST"
  body?: unknown
  signal?: AbortSignal
  fetch?: typeof fetch
}

const eventKinds = new Set<DevelopStreamEventKind>([
  "session",
  "status",
  "text",
  "error",
  "idle",
  "done",
])

const parseEvent = (frame: string): DevelopStreamEvent | undefined => {
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.replace(/^data:\s?/, ""))
    .join("\n")
  if (!data) return undefined

  let value: unknown
  try {
    value = JSON.parse(data)
  } catch {
    throw new Error("Malformed Develop SSE data")
  }
  if (
    typeof value !== "object" ||
    value === null ||
    typeof (value as DevelopStreamEvent).sequence !== "number" ||
    !eventKinds.has((value as DevelopStreamEvent).kind) ||
    typeof (value as DevelopStreamEvent).data !== "string"
  ) {
    throw new Error("Invalid Develop SSE event")
  }
  return value as DevelopStreamEvent
}

export async function* streamDevelopTurn({
  url,
  token,
  method = "GET",
  body,
  signal,
  fetch: fetchImplementation = globalThis.fetch,
}: StreamDevelopTurnOptions): AsyncGenerator<DevelopStreamEvent> {
  const headers = new Headers({
    Accept: "text/event-stream",
    Authorization: `Bearer ${token}`,
  })
  if (body !== undefined) headers.set("Content-Type", "application/json")
  const response = await fetchImplementation(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
  if (!response.ok) throw new Error(`Develop stream failed: ${response.status}`)
  if (!response.body) throw new Error("Develop stream response has no body")

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let cancellation: Promise<void> | undefined
  const abort = () => {
    cancellation = reader.cancel(signal?.reason)
  }
  signal?.addEventListener("abort", abort, { once: true })
  let buffer = ""
  try {
    while (!signal?.aborted) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += value.replace(/\r\n?/g, "\n")
      const frames = buffer.split("\n\n")
      buffer = frames.pop() ?? ""
      for (const frame of frames) {
        const event = parseEvent(frame)
        if (event) yield event
      }
    }
  } finally {
    signal?.removeEventListener("abort", abort)
    await cancellation
    reader.releaseLock()
  }
}
