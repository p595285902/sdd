import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import {
  hasPreviewRuntime,
  type PreviewContext,
  requestPreview,
} from "./preview"
import {
  emptyPreviewOutput,
  executionActive,
  mergePreviewEvents,
  type PreviewExecution,
  type PreviewExecutionEvent,
  type PreviewOutput,
  streamPreviewExecution,
} from "./previewExecution"

export const previewExecutionsKey = (chatId: string) =>
  ["development-preview-executions", chatId] as const
const outputKey = (chatId: string, executionId: string) =>
  ["development-preview-output", chatId, executionId] as const

export function usePreviewControls({
  chatId,
  workspaceReady,
  setupPending,
  open,
}: {
  chatId?: string
  workspaceReady: boolean
  setupPending: boolean
  open: boolean
}) {
  const queryClient = useQueryClient()
  const contextKey = ["development-preview-context", chatId]
  const executionsQuery = useQuery({
    queryKey: previewExecutionsKey(chatId ?? ""),
    enabled: Boolean(chatId),
    retry: false,
    queryFn: async ({ signal }) => {
      const result = await requestPreview<{ data: PreviewExecution[] }>(
        chatId ?? "",
        "executions",
        "GET",
        signal,
      )
      return result.data.filter((execution) => execution.chat_id === chatId)
    },
    refetchInterval: (query) =>
      query.state.data?.some(executionActive) ? 2000 : false,
  })
  const contextQuery = useQuery({
    queryKey: contextKey,
    enabled: Boolean(chatId) && open && workspaceReady,
    gcTime: 0,
    retry: false,
    queryFn: ({ signal }) =>
      requestPreview<PreviewContext>(chatId ?? "", "context", "GET", signal),
    refetchInterval: (query) =>
      hasPreviewRuntime(query.state.data) ? 2000 : false,
  })
  const action = useMutation({
    mutationFn: ({ id, name }: { id: string; name: "launch" | "restart" }) =>
      requestPreview<PreviewContext & { execution?: PreviewExecution }>(
        id,
        name,
        "POST",
        undefined,
        {},
      ),
    onMutate: async ({ id }) => {
      await Promise.all([
        queryClient.cancelQueries({
          queryKey: ["development-preview-context", id],
        }),
        queryClient.cancelQueries({
          queryKey: ["development-preview-session", id],
        }),
      ])
    },
    onSuccess: (result, { id }) => {
      if (result.execution?.chat_id === id) {
        const execution = result.execution
        queryClient.setQueryData<PreviewExecution[]>(
          previewExecutionsKey(id),
          (current = []) => [
            ...current.filter((item) => item.id !== execution.id),
            execution,
          ],
        )
      }
    },
    onSettled: async (_result, _error, { id }) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["development-preview-context", id],
        }),
        queryClient.invalidateQueries({ queryKey: previewExecutionsKey(id) }),
      ])
    },
  })
  const context = contextQuery.data
  const actionForChat = action.variables?.id === chatId
  const actionPending = actionForChat && action.isPending
  const executions = executionsQuery.data ?? []
  const starting =
    actionPending ||
    executions.some((execution) => execution.status === "starting") ||
    context?.state === "starting"
  const running =
    executions.some(executionActive) ||
    context?.state === "ready" ||
    context?.state === "running"
  return {
    contextQuery,
    executionsQuery,
    executions,
    actionPending,
    actionError: actionForChat ? action.error : null,
    sessionGeneration: actionForChat ? action.submittedAt : 0,
    starting,
    busy: starting || running,
    launchDisabled:
      !chatId ||
      !workspaceReady ||
      setupPending ||
      starting ||
      running ||
      executionsQuery.isPending ||
      contextQuery.isPending,
    launch: () => {
      if (chatId && !starting && !running)
        action.mutate({ id: chatId, name: "launch" })
    },
    restart: () => {
      if (chatId && !actionPending)
        action.mutate({ id: chatId, name: "restart" })
    },
  }
}

export type PreviewControls = ReturnType<typeof usePreviewControls>

export function usePreviewOutput(chatId: string, execution: PreviewExecution) {
  const queryClient = useQueryClient()
  const [connectionError, setConnectionError] = useState("")
  const [connectionGeneration, setConnectionGeneration] = useState(0)
  const executionId = execution.id
  const active = executionActive(execution)
  const eventsQuery = useQuery({
    queryKey: outputKey(chatId, executionId),
    retry: false,
    queryFn: async ({ signal }) => {
      let output =
        queryClient.getQueryData<PreviewOutput>(
          outputKey(chatId, executionId),
        ) ?? emptyPreviewOutput()
      let cursor = output.lastSequence
      for (;;) {
        const response = await requestPreview<{
          data: PreviewExecutionEvent[]
          has_more?: boolean
          next_sequence?: number
        }>(
          chatId,
          `executions/${executionId}/events?after=${cursor}`,
          "GET",
          signal,
        )
        output = mergePreviewEvents(output, executionId, response.data)
        if (!response.has_more) break
        const next = response.next_sequence ?? output.lastSequence
        if (next <= cursor)
          throw new Error("Preview output replay cursor did not advance.")
        cursor = next
      }
      const latest = queryClient.getQueryData<PreviewOutput>(
        outputKey(chatId, executionId),
      )
      return latest
        ? mergePreviewEvents(output, executionId, latest.events)
        : output
    },
  })
  const loaded = eventsQuery.isSuccess
  // biome-ignore lint/correctness/useExhaustiveDependencies: Explicit Reconnect changes the generation to restart this bounded attachment.
  useEffect(() => {
    if (!loaded || !active) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let releaseDelay: (() => void) | undefined
    setConnectionError("")
    const connect = async () => {
      // A stream disconnect never launches/restarts anything. Retry at most three
      // times per attachment; explicit Reconnect resumes after the saved cursor.
      for (
        let attempt = 0;
        attempt < 4 && !controller.signal.aborted;
        attempt++
      ) {
        try {
          const cursor =
            queryClient.getQueryData<PreviewOutput>(
              outputKey(chatId, executionId),
            )?.lastSequence ?? 0
          for await (const event of streamPreviewExecution({
            url: `${import.meta.env.VITE_API_URL ?? ""}/api/v1/develop/chats/${chatId}/preview/executions/${executionId}/stream?after=${cursor}`,
            token: localStorage.getItem("access_token") ?? "",
            signal: controller.signal,
          })) {
            if (controller.signal.aborted || event.execution_id !== executionId)
              continue
            const previousSequence =
              queryClient.getQueryData<PreviewOutput>(
                outputKey(chatId, executionId),
              )?.lastSequence ?? 0
            if (event.sequence <= previousSequence) continue
            queryClient.setQueryData<PreviewOutput>(
              outputKey(chatId, executionId),
              (current) =>
                mergePreviewEvents(
                  current ?? emptyPreviewOutput(),
                  executionId,
                  [event],
                ),
            )
            if (event.kind === "status" && event.payload.status) {
              queryClient.setQueryData<PreviewExecution[]>(
                previewExecutionsKey(chatId),
                (current) =>
                  current?.map((item) =>
                    item.id === executionId &&
                    event.sequence >= item.last_sequence
                      ? {
                          ...item,
                          status: event.payload.status ?? item.status,
                          ready: event.payload.ready ?? item.ready,
                          updated_at: event.created_at,
                          last_sequence: Math.max(
                            item.last_sequence,
                            event.sequence,
                          ),
                        }
                      : item,
                  ),
              )
            }
          }
          if (controller.signal.aborted) return
          throw new Error("Preview output disconnected.")
        } catch (error) {
          if (controller.signal.aborted) return
          if (attempt === 3) {
            setConnectionError(
              error instanceof Error
                ? error.message
                : "Preview output disconnected.",
            )
            return
          }
          await new Promise<void>((resolve) => {
            releaseDelay = resolve
            timer = setTimeout(resolve, 500 * 2 ** attempt)
          })
        }
      }
    }
    void connect()
    return () => {
      controller.abort()
      clearTimeout(timer)
      releaseDelay?.()
    }
  }, [chatId, executionId, active, loaded, connectionGeneration, queryClient])

  // Fetch the final durable tail if status polling sees termination before SSE.
  useEffect(() => {
    if (!active)
      void queryClient.invalidateQueries({
        queryKey: outputKey(chatId, executionId),
      })
  }, [active, chatId, executionId, queryClient])

  return {
    ...eventsQuery,
    connectionError,
    reconnect: async () => {
      setConnectionError("")
      await eventsQuery.refetch()
      setConnectionGeneration((value) => value + 1)
    },
  }
}
