import type { DevelopmentMessagePublic } from "@/client"

import type { DevelopStreamEvent } from "./stream"

export const DEVELOP_CACHE_LIMIT = 5

export type DevelopConversation = {
  messages: DevelopmentMessagePublic[]
  activity: string[]
  response: string
  lastSequence: number
  running: boolean
  startedAt: number | null
  error: string | null
}

export type DevelopConversationCache = Record<string, DevelopConversation>

export const emptyConversation = (): DevelopConversation => ({
  messages: [],
  activity: [],
  response: "",
  lastSequence: 0,
  running: false,
  startedAt: null,
  error: null,
})

export const cacheConversation = (
  cache: DevelopConversationCache,
  chatId: string,
  conversation: DevelopConversation,
): DevelopConversationCache => {
  const entries = Object.entries(cache).filter(([id]) => id !== chatId)
  entries.push([chatId, conversation])
  return Object.fromEntries(entries.slice(-DEVELOP_CACHE_LIMIT))
}

export const reconcileMessages = (
  conversation: DevelopConversation,
  persisted: DevelopmentMessagePublic[],
): DevelopConversation => {
  const optimistic = conversation.messages.filter(
    (message) =>
      message.id.startsWith("optimistic-") &&
      !persisted.some(
        ({ role, content }) =>
          role === message.role && content === message.content,
      ),
  )
  const streamPersisted =
    !conversation.running &&
    conversation.response.length > 0 &&
    persisted.some(
      ({ role, content }) =>
        role === "assistant" && content === conversation.response,
    )
  return {
    ...conversation,
    messages: conversation.running ? [...persisted, ...optimistic] : persisted,
    activity: streamPersisted ? [] : conversation.activity,
    response: streamPersisted ? "" : conversation.response,
    startedAt: streamPersisted ? null : conversation.startedAt,
  }
}

export const startOptimisticTurn = (
  conversation: DevelopConversation,
  chatId: string,
  content: string,
  now = Date.now(),
): DevelopConversation => ({
  ...conversation,
  messages: [
    ...conversation.messages,
    {
      id: `optimistic-${now}`,
      chat_id: chatId,
      role: "user",
      content,
      created_at: new Date(now).toISOString(),
    },
  ],
  activity: [],
  response: "",
  lastSequence: 0,
  running: true,
  startedAt: now,
  error: null,
})

export const applyStreamEvent = (
  conversation: DevelopConversation,
  event: DevelopStreamEvent,
): DevelopConversation => {
  if (event.sequence <= conversation.lastSequence) return conversation

  const next = { ...conversation, lastSequence: event.sequence }
  if (event.kind === "status") {
    return {
      ...next,
      activity: [...next.activity, event.data],
      running: true,
      startedAt: next.startedAt ?? Date.now(),
    }
  }
  if (event.kind === "text") {
    return { ...next, response: next.response + event.data }
  }
  if (event.kind === "error") {
    return { ...next, error: event.data, running: false }
  }
  if (event.kind === "done") {
    return { ...next, running: false }
  }
  return next
}
