import { useState } from "react"

import { Button } from "@/components/ui/button"

import {
  executionActive,
  type PreviewExecution,
  previewEventText,
  safePreviewText,
} from "./previewExecution"
import { usePreviewOutput } from "./usePreviewExecution"

export function DevelopPreviewExecution({
  chatId,
  execution,
}: {
  chatId: string
  execution: PreviewExecution
}) {
  const output = usePreviewOutput(chatId, execution)
  const [expanded, setExpanded] = useState(() => executionActive(execution))
  const events = output.data?.events ?? []
  const truncated =
    execution.truncated_bytes > 0 &&
    !events.some((event) =>
      ["truncated", "output_truncated", "gap"].includes(event.kind),
    )
  const workflow =
    execution.workflow ??
    (execution as PreviewExecution & { workflow_snapshot?: unknown })
      .workflow_snapshot
  const workflowText =
    workflow == null
      ? ""
      : typeof workflow === "string"
        ? workflow
        : JSON.stringify(workflow, null, 2)
  return (
    <article
      aria-label="Preview execution"
      className="min-w-0 rounded-md border px-4 py-3 text-sm"
      data-execution-id={execution.id}
    >
      <details
        open={expanded}
        onToggle={(event) => setExpanded(event.currentTarget.open)}
      >
        <summary className="cursor-pointer text-sm font-medium">
          Preview execution · {execution.status}
          {execution.ready ? " · Application ready" : ""}
        </summary>
        <div className="mt-3 min-w-0 space-y-2">
          <p className="text-xs text-muted-foreground">
            {executionActive(execution)
              ? "Live preview operation"
              : "Completed preview operation"}
            {" · "}
            <time dateTime={execution.created_at}>
              {new Date(execution.created_at).toLocaleString()}
            </time>
          </p>
          {workflowText && (
            <section aria-label="Preview workflow">
              <pre className="whitespace-pre-wrap break-words font-mono text-xs">
                {safePreviewText(workflowText)}
              </pre>
            </section>
          )}
          {output.isPending && (
            <p role="status">Loading saved preview output…</p>
          )}
          {truncated && (
            <p role="status">
              Output truncated: {execution.truncated_bytes} bytes omitted.
            </p>
          )}
          {Boolean(output.data?.omittedBytes) && (
            <p role="status">
              Output truncated in this browser: {output.data?.omittedBytes}{" "}
              bytes omitted.
            </p>
          )}
          <pre
            role="log"
            aria-label="Preview command output"
            className="max-h-96 overflow-y-auto whitespace-pre-wrap break-words rounded bg-muted p-3 font-mono text-xs [overflow-wrap:anywhere]"
          >
            {events.map((event) => (
              <span
                className={
                  event.kind === "stderr" ? "text-destructive" : undefined
                }
                data-stream={event.payload.stream ?? event.kind}
                key={event.sequence}
              >
                {previewEventText(event)}
              </span>
            ))}
          </pre>
          {(output.error || output.connectionError) && (
            <div className="space-y-2">
              <p role="alert" className="text-xs text-destructive">
                {output.error?.message ?? output.connectionError} Saved output
                is retained.
              </p>
              <Button
                onClick={() => void output.reconnect()}
                size="sm"
                variant="outline"
              >
                Reconnect preview output
              </Button>
            </div>
          )}
        </div>
      </details>
    </article>
  )
}
