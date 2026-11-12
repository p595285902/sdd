export type PreviewExecutionStatus =
  | "starting"
  | "running"
  | "failed"
  | "stopped"
  | "interrupted"

export type PreviewExecution = {
  id: string
  chat_id: string
  created_at: string
  updated_at: string
  status: PreviewExecutionStatus
  ready: boolean
  workflow: unknown
  last_sequence: number
  truncated_bytes: number
}

export type PreviewExecutionEvent = {
  execution_id: string
  sequence: number
  kind:
    | "command_start"
    | "stdout"
    | "stderr"
    | "command_exit"
    | "status"
    | "truncated"
    | "output_truncated"
    | "gap"
  payload: {
    text?: string
    stream?: string
    argv?: string[]
    cwd?: string
    exit_code?: number | null
    status?: PreviewExecutionStatus
    ready?: boolean
    reason?: string
    truncated_bytes?: number
    dropped_bytes?: number
    total_dropped_bytes?: number
    through_cursor?: number
  }
  created_at: string
}

export type PreviewOutput = {
  events: PreviewExecutionEvent[]
  lastSequence: number
  omittedBytes: number
}

export const emptyPreviewOutput = (): PreviewOutput => ({
  events: [],
  lastSequence: 0,
  omittedBytes: 0,
})

export const executionActive = (execution: PreviewExecution) =>
  execution.status === "starting" || execution.status === "running"

// Project output is text, never terminal instructions, HTML or Markdown. Strip
// OSC/DCS (including hyperlinks/clipboard), CSI, other escapes and bidi controls.
// biome-ignore-start lint/suspicious/noControlCharactersInRegex: Terminal controls are intentionally matched for removal.
export function safePreviewText(value: string): string {
  return value
    .replace(/(?:\u001b\]|\u009d)[\s\S]*?(?:\u0007|\u001b\\|\u009c|$)/g, "")
    .replace(
      /(?:\u001b[P^_X]|[\u0090\u0098\u009e\u009f])[\s\S]*?(?:\u001b\\|\u009c|$)/g,
      "",
    )
    .replace(/(?:\u001b\[|\u009b)[0-?]*[ -/]*[@-~]/g, "")
    .replace(/\u001b[ -/]*[@-~]/g, "")
    .replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f؜‎‏‪-‮⁦-⁩]/g, "")
}
// biome-ignore-end lint/suspicious/noControlCharactersInRegex: Terminal controls are intentionally matched for removal.

// Retain lifecycle/command metadata even if a long-running watch produces more
// output than the browser budget. The cursor is independent of retained rows.
export function mergePreviewEvents(
  current: PreviewOutput,
  executionId: string,
  incoming: PreviewExecutionEvent[],
  outputBudget = 1_048_576,
): PreviewOutput {
  const added = new Map<number, PreviewExecutionEvent>()
  for (const event of incoming) {
    if (
      event.execution_id === executionId &&
      event.sequence > current.lastSequence
    ) {
      added.set(event.sequence, event)
    }
  }
  if (!added.size) return current
  const events = [
    ...current.events,
    ...[...added.values()].sort((a, b) => a.sequence - b.sequence),
  ]
  const encoder = new TextEncoder()
  let bytes = 0
  let omittedBytes = current.omittedBytes
  const retained: PreviewExecutionEvent[] = []
  for (const event of events.slice().reverse()) {
    const output = event.kind === "stdout" || event.kind === "stderr"
    const size = output ? encoder.encode(event.payload.text ?? "").length : 0
    if (output && bytes + size > outputBudget) omittedBytes += size
    else {
      bytes += size
      retained.push(event)
    }
  }
  return {
    events: retained.reverse(),
    lastSequence: Math.max(current.lastSequence, ...added.keys()),
    omittedBytes,
  }
}

export function previewEventText(event: PreviewExecutionEvent): string {
  const payload = event.payload
  const omittedBytes =
    payload.truncated_bytes ??
    payload.total_dropped_bytes ??
    payload.dropped_bytes
  switch (event.kind) {
    case "command_start":
      return safePreviewText(
        `${payload.cwd ? `[${payload.cwd}] ` : ""}$ ${payload.argv?.join(" ") || payload.text || "Command started"}\n`,
      )
    case "command_exit":
      return safePreviewText(
        `\nCommand exited${payload.exit_code == null ? "" : ` (${payload.exit_code})`}${payload.reason ? `: ${payload.reason}` : ""}\n`,
      )
    case "status":
      return safePreviewText(
        `\n${payload.status ?? "Status updated"}${payload.reason ? `: ${payload.reason}` : ""}\n`,
      )
    case "truncated":
    case "output_truncated":
    case "gap":
      return safePreviewText(
        `\n[Output truncated${omittedBytes ? `: ${omittedBytes} bytes omitted` : ""}${payload.through_cursor ? ` through output cursor ${payload.through_cursor}` : ""}${payload.reason ? `: ${payload.reason}` : ""}]\n`,
      )
    default:
      return safePreviewText(payload.text ?? "")
  }
}

export function previewTimeline<T extends { id: string; created_at: string }>(
  messages: T[],
  executions: PreviewExecution[],
) {
  return [
    ...messages.map((message) => ({
      kind: "message" as const,
      id: message.id,
      created_at: message.created_at,
      message,
    })),
    ...executions.map((execution) => ({
      kind: "execution" as const,
      id: execution.id,
      created_at: execution.created_at,
      execution,
    })),
  ].sort(
    (a, b) =>
      Date.parse(a.created_at) - Date.parse(b.created_at) ||
      a.id.localeCompare(b.id),
  )
}

const eventKinds = new Set([
  "command_start",
  "stdout",
  "stderr",
  "command_exit",
  "status",
  "truncated",
  "output_truncated",
  "gap",
])

function parsePreviewEvent(frame: string): PreviewExecutionEvent | undefined {
  const lines = frame.split("\n")
  if (!lines.some((line) => /^event:\s*preview-event\s*$/.test(line))) return
  const data = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.replace(/^data:\s?/, ""))
    .join("\n")
  const event = JSON.parse(data) as PreviewExecutionEvent
  if (
    !event ||
    typeof event.execution_id !== "string" ||
    !Number.isSafeInteger(event.sequence) ||
    event.sequence < 1 ||
    !eventKinds.has(event.kind) ||
    !event.payload ||
    typeof event.payload !== "object"
  )
    throw new Error("Invalid preview output event")
  return event
}

export async function* streamPreviewExecution({
  url,
  token,
  signal,
  fetch: fetchImplementation = globalThis.fetch,
}: {
  url: string
  token: string
  signal: AbortSignal
  fetch?: typeof fetch
}): AsyncGenerator<PreviewExecutionEvent> {
  const response = await fetchImplementation(url, {
    headers: { Accept: "text/event-stream", Authorization: `Bearer ${token}` },
    signal,
  })
  if (!response.ok)
    throw new Error(`Preview output stream failed (${response.status}).`)
  if (!response.body) throw new Error("Preview output stream has no body.")
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const abort = () => {
    void reader.cancel().catch(() => undefined)
  }
  signal.addEventListener("abort", abort, { once: true })
  let buffer = ""
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read()
      buffer += done
        ? decoder.decode()
        : decoder.decode(value, { stream: true })
      let separator = /\r?\n\r?\n/.exec(buffer)
      while (separator) {
        const frame = buffer.slice(0, separator.index).replace(/\r\n/g, "\n")
        buffer = buffer.slice(separator.index + separator[0].length)
        const event = parsePreviewEvent(frame)
        if (event) yield event
        separator = /\r?\n\r?\n/.exec(buffer)
      }
      if (buffer.length > 2_097_152)
        throw new Error("Preview output frame exceeds its limit.")
      if (done) break
    }
  } finally {
    signal.removeEventListener("abort", abort)
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
