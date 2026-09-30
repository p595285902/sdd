import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import {
  GitBranch,
  History,
  Loader2,
  MessageSquarePlus,
  PanelRight,
  Pencil,
  Rocket,
  Send,
  Square,
  Trash2,
  X,
} from "lucide-react"
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react"

import {
  type DevelopmentChatPublic,
  DevelopService,
  type PresenceMode,
} from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import useCustomToast from "@/hooks/useCustomToast"
import { handleError } from "@/utils"

import { DevelopMarkdown } from "./DevelopMarkdown"
import {
  applyStreamEvent,
  cacheConversation,
  type DevelopConversation,
  type DevelopConversationCache,
  emptyConversation,
  reconcileMessages,
  startOptimisticTurn,
} from "./state"
import { streamDevelopTurn } from "./stream"

const elapsed = (startedAt: number | null, now: number) => {
  if (!startedAt) return "0:00"
  const seconds = Math.max(0, Math.floor((now - startedAt) / 1000))
  return `${Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, "0")}`
}

export function DevelopWorkspace() {
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()
  const [selectedId, setSelectedId] = useState<string | "new" | null>(null)
  const [firstMessage, setFirstMessage] = useState("")
  const [draft, setDraft] = useState("")
  const [renameTitle, setRenameTitle] = useState<string | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [mobilePanel, setMobilePanel] = useState<"history" | "context" | null>(
    null,
  )
  const [cache, setCache] = useState<DevelopConversationCache>({})
  const [now, setNow] = useState(Date.now())
  const streams = useRef(new Map<string, AbortController>())
  const viewport = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)

  const chatsQuery = useQuery({
    queryKey: ["development-chats"],
    queryFn: async () => (await DevelopService.readDevelopmentChats()).data,
  })
  const chats = chatsQuery.data?.data ?? []
  const effectiveId = selectedId === null ? chats[0]?.id : selectedId
  const selected =
    effectiveId === "new"
      ? undefined
      : chats.find(({ id }) => id === effectiveId)
  const conversation = selected
    ? (cache[selected.id] ?? emptyConversation())
    : emptyConversation()

  const updateConversation = useCallback(
    (
      chatId: string,
      update: (value: DevelopConversation) => DevelopConversation,
    ) => {
      setCache((current) =>
        cacheConversation(
          current,
          chatId,
          update(current[chatId] ?? emptyConversation()),
        ),
      )
      if (pinned.current) {
        requestAnimationFrame(() => {
          if (viewport.current) {
            viewport.current.scrollTop = viewport.current.scrollHeight
          }
        })
      }
    },
    [],
  )

  const workspaceQuery = useQuery({
    enabled: Boolean(selected),
    queryKey: ["development-workspace", selected?.id],
    queryFn: async () =>
      (
        await DevelopService.readDevelopmentWorkspace({
          path: { chat_id: selected?.id ?? "" },
        })
      ).data,
  })
  const messagesQuery = useInfiniteQuery({
    enabled: Boolean(selected),
    queryKey: ["development-messages", selected?.id],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await DevelopService.readDevelopmentMessages({
          path: { chat_id: selected?.id ?? "" },
          query: pageParam ? { before: pageParam } : {},
        })
      ).data,
    getNextPageParam: (page) =>
      page.has_more ? (page.next_cursor ?? undefined) : undefined,
  })

  useEffect(() => {
    if (!selected || !messagesQuery.data) return
    const persisted = messagesQuery.data.pages
      .slice()
      .reverse()
      .flatMap(({ data }) => data)
    updateConversation(selected.id, (current) =>
      reconcileMessages(current, persisted),
    )
  }, [messagesQuery.data, selected, updateConversation])

  useEffect(() => {
    if (!conversation.running) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [conversation.running])

  const finishStream = useCallback(
    async (chatId: string) => {
      streams.current.delete(chatId)
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["development-messages", chatId],
        }),
        queryClient.invalidateQueries({ queryKey: ["development-chats"] }),
      ])
    },
    [queryClient],
  )

  const consumeStream = useCallback(
    async (
      chatId: string,
      method: "GET" | "POST",
      content?: string,
      suffix?: string,
    ) => {
      streams.current.get(chatId)?.abort()
      const controller = new AbortController()
      streams.current.set(chatId, controller)
      try {
        const streamSuffix =
          suffix ??
          (method === "POST"
            ? "messages/explore/stream"
            : "turns/current/stream")
        for await (const event of streamDevelopTurn({
          url: `/api/v1/develop/chats/${chatId}/${streamSuffix}`,
          token: localStorage.getItem("access_token") ?? "",
          method,
          body: content === undefined ? undefined : { content },
          signal: controller.signal,
        })) {
          updateConversation(chatId, (current) =>
            applyStreamEvent(current, event),
          )
        }
        await finishStream(chatId)
      } catch (error) {
        if (controller.signal.aborted) {
          streams.current.delete(chatId)
          return
        }
        if (method === "GET" && String(error).includes("404")) return
        const message = error instanceof Error ? error.message : "Stream failed"
        updateConversation(chatId, (current) => ({
          ...current,
          error: message,
          running: false,
        }))
        showErrorToast(message)
      }
    },
    [finishStream, showErrorToast, updateConversation],
  )

  useEffect(() => {
    if (!selected || streams.current.has(selected.id)) return
    void consumeStream(selected.id, "GET")
    return () => streams.current.get(selected.id)?.abort()
  }, [selected, consumeStream])

  const createChat = useMutation({
    mutationFn: async (content: string) =>
      (await DevelopService.createDevelopmentChat({ body: { content } })).data,
    onError: handleError.bind(showErrorToast),
    onSuccess: async (chat) => {
      setFirstMessage("")
      setSelectedId(chat.id)
      setMobilePanel(null)
      await queryClient.invalidateQueries({ queryKey: ["development-chats"] })
    },
  })
  const renameChat = useMutation({
    mutationFn: async ({
      chat,
      title,
    }: {
      chat: DevelopmentChatPublic
      title: string
    }) =>
      (
        await DevelopService.renameDevelopmentChat({
          path: { chat_id: chat.id },
          body: { title },
        })
      ).data,
    onError: handleError.bind(showErrorToast),
    onSuccess: async () => {
      setRenameTitle(null)
      await queryClient.invalidateQueries({ queryKey: ["development-chats"] })
    },
  })
  const setupWorkspace = useMutation({
    mutationFn: async (chatId: string) =>
      (
        await DevelopService.setupDevelopmentWorkspace({
          path: { chat_id: chatId },
        })
      ).data,
    onError: handleError.bind(showErrorToast),
    onSuccess: (workspace) =>
      queryClient.setQueryData(
        ["development-workspace", selected?.id],
        workspace,
      ),
  })
  const presence = useMutation({
    mutationFn: async (mode: PresenceMode) =>
      DevelopService.updateDevelopmentPresence({
        path: { chat_id: selected?.id ?? "" },
        body: { presence_mode: mode },
      }),
    onError: handleError.bind(showErrorToast),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["development-chats"] }),
  })
  const stopTurn = useMutation({
    mutationFn: (chatId: string) =>
      DevelopService.stopCurrentTurn({ path: { chat_id: chatId } }),
    onError: handleError.bind(showErrorToast),
    onSuccess: async () => {
      if (!selected) return
      streams.current.get(selected.id)?.abort()
      updateConversation(selected.id, (current) => ({
        ...current,
        running: false,
      }))
      await finishStream(selected.id)
    },
  })
  const propose = useMutation({
    mutationFn: async (chatId: string) =>
      (
        await DevelopService.proposeDevelopmentChat({
          path: { chat_id: chatId },
        })
      ).data,
    onError: handleError.bind(showErrorToast),
    onSuccess: async (proposal) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: ["development-messages", proposal.chat_id],
        }),
        queryClient.invalidateQueries({ queryKey: ["development-chats"] }),
      ])
    },
  })
  const rejectProposal = useMutation({
    mutationFn: async ({
      chatId,
      messageId,
    }: {
      chatId: string
      messageId: string
    }) =>
      (
        await DevelopService.rejectDevelopmentProposal({
          path: { chat_id: chatId, message_id: messageId },
        })
      ).data,
    onError: handleError.bind(showErrorToast),
    onSuccess: async (proposal) => {
      await queryClient.invalidateQueries({
        queryKey: ["development-messages", proposal.chat_id],
      })
    },
  })
  const deleteChat = useMutation({
    mutationFn: (chat: DevelopmentChatPublic) =>
      DevelopService.deleteDevelopmentChat({
        path: { chat_id: chat.id },
        query: { confirm: true },
      }),
    onError: handleError.bind(showErrorToast),
    onSuccess: async () => {
      setDeleteOpen(false)
      setSelectedId(null)
      await queryClient.invalidateQueries({ queryKey: ["development-chats"] })
    },
  })

  const submitFirst = (event: FormEvent) => {
    event.preventDefault()
    const content = firstMessage.trim()
    if (content) createChat.mutate(content)
  }
  const submitRename = (event: FormEvent) => {
    event.preventDefault()
    const title = renameTitle?.trim()
    if (selected && title) renameChat.mutate({ chat: selected, title })
  }
  const submitExploration = (event: FormEvent) => {
    event.preventDefault()
    const content = draft.trim()
    if (!selected || !content || conversation.running) return
    updateConversation(selected.id, (current) =>
      startOptimisticTurn(current, selected.id, content),
    )
    setDraft("")
    pinned.current = true
    void consumeStream(selected.id, "POST", content)
  }
  const approveProposal = (messageId: string) => {
    if (!selected || conversation.running) return
    updateConversation(selected.id, (current) => ({
      ...current,
      activity: [],
      response: "",
      lastSequence: 0,
      running: true,
      startedAt: Date.now(),
      error: null,
    }))
    pinned.current = true
    void consumeStream(
      selected.id,
      "POST",
      undefined,
      `messages/${messageId}/approve/stream`,
    )
  }
  const selectChat = (chatId: string) => {
    setSelectedId(chatId)
    setRenameTitle(null)
    setMobilePanel(null)
    pinned.current = true
  }

  const history = (
    <aside className="flex h-full min-h-0 flex-col border-r bg-background">
      <div className="flex h-14 items-center justify-between border-b px-3">
        <h2 className="text-sm font-semibold">Recent chats</h2>
        <div className="flex gap-1">
          <Button
            aria-label="New Development Chat"
            onClick={() => {
              setSelectedId("new")
              setMobilePanel(null)
            }}
            size="icon-sm"
            title="New Development Chat"
            variant="ghost"
          >
            <MessageSquarePlus />
          </Button>
          {mobilePanel === "history" && (
            <Button
              aria-label="Close panel"
              onClick={() => setMobilePanel(null)}
              size="icon-sm"
              variant="ghost"
            >
              <X />
            </Button>
          )}
        </div>
      </div>
      <nav
        aria-label="Development Chats"
        className="min-h-0 overflow-y-auto p-2"
      >
        {chats.map((chat) => (
          <button
            className={`mb-1 w-full truncate rounded-sm px-3 py-2 text-left text-sm ${selected?.id === chat.id ? "bg-accent font-medium" : "hover:bg-accent/60"}`}
            key={chat.id}
            onClick={() => selectChat(chat.id)}
            type="button"
          >
            {chat.title}
          </button>
        ))}
        {!chatsQuery.isPending && chats.length === 0 && (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No chats yet
          </p>
        )}
      </nav>
    </aside>
  )

  const context = (
    <aside
      aria-label="Development context"
      className="h-full border-l bg-background"
    >
      <div className="flex h-14 items-center justify-between border-b px-4">
        <h2 className="text-sm font-semibold">Context</h2>
        {mobilePanel === "context" && (
          <Button
            aria-label="Close panel"
            onClick={() => setMobilePanel(null)}
            size="icon-sm"
            variant="ghost"
          >
            <X />
          </Button>
        )}
      </div>
      <div className="space-y-6 p-4 text-sm">
        <section>
          <h3 className="font-medium">Repository</h3>
          <p className="mt-1 text-muted-foreground">
            {workspaceQuery.data?.ready
              ? "Demo repository ready"
              : "Setup required"}
          </p>
        </section>
        <section>
          <h3 className="mb-2 font-medium">Presence Mode</h3>
          <fieldset aria-label="Presence Mode" className="grid gap-2">
            {(
              [
                ["stop_when_i_leave", "Stop when I leave"],
                ["continue_in_background", "Continue in background"],
              ] as const
            ).map(([mode, label]) => (
              <Button
                aria-pressed={selected?.presence_mode === mode}
                disabled={!selected || presence.isPending}
                key={mode}
                onClick={() => presence.mutate(mode)}
                size="sm"
                variant={
                  selected?.presence_mode === mode ? "default" : "outline"
                }
              >
                {label}
              </Button>
            ))}
          </fieldset>
        </section>
        {conversation.running && (
          <p aria-live="polite">
            Agent Turn running {elapsed(conversation.startedAt, now)}
          </p>
        )}
      </div>
    </aside>
  )

  return (
    <div className="flex min-h-[calc(100vh-7rem)] flex-col">
      <header className="flex items-center justify-between border-b pb-3">
        <div>
          <h1 className="text-2xl font-bold">Develop</h1>
          <p className="text-sm text-muted-foreground">Development Chats</p>
        </div>
        <div className="flex gap-1 md:hidden">
          <Button
            aria-label="Open chat history"
            onClick={() => setMobilePanel("history")}
            size="icon"
            variant="outline"
          >
            <History />
          </Button>
          <Button
            aria-label="Open development context"
            onClick={() => setMobilePanel("context")}
            size="icon"
            variant="outline"
          >
            <PanelRight />
          </Button>
        </div>
      </header>

      <div className="relative grid min-h-0 flex-1 overflow-hidden md:grid-cols-[17rem_minmax(0,1fr)] lg:grid-cols-[17rem_minmax(0,1fr)_17rem]">
        <div className="hidden min-h-0 md:block">{history}</div>
        <section
          aria-label="Conversation"
          className="flex min-h-[32rem] min-w-0 flex-col"
        >
          {selected ? (
            <>
              <div className="flex min-h-14 items-center justify-between border-b px-3">
                {renameTitle !== null ? (
                  <form className="flex w-full gap-2" onSubmit={submitRename}>
                    <Input
                      aria-label="Development Chat title"
                      autoFocus
                      maxLength={255}
                      onChange={(event) => setRenameTitle(event.target.value)}
                      value={renameTitle}
                    />
                    <Button disabled={!renameTitle.trim()} type="submit">
                      Save
                    </Button>
                    <Button
                      onClick={() => setRenameTitle(null)}
                      type="button"
                      variant="ghost"
                    >
                      Cancel
                    </Button>
                  </form>
                ) : (
                  <>
                    <h2 className="truncate font-semibold">{selected.title}</h2>
                    <div className="flex gap-1">
                      <Button
                        aria-label={
                          workspaceQuery.data?.ready
                            ? "Demo repository ready"
                            : "Set up demo repository"
                        }
                        disabled={
                          workspaceQuery.isPending ||
                          workspaceQuery.data?.ready ||
                          !workspaceQuery.data?.setup_available ||
                          setupWorkspace.isPending
                        }
                        onClick={() => setupWorkspace.mutate(selected.id)}
                        size="icon-sm"
                        title="Set up demo repository"
                        variant="outline"
                      >
                        <GitBranch />
                      </Button>
                      <Button
                        aria-label="Rename Development Chat"
                        onClick={() => setRenameTitle(selected.title)}
                        size="icon-sm"
                        title="Rename Development Chat"
                        variant="ghost"
                      >
                        <Pencil />
                      </Button>
                      <Button
                        aria-label="Delete Development Chat"
                        onClick={() => setDeleteOpen(true)}
                        size="icon-sm"
                        title="Delete Development Chat"
                        variant="ghost"
                      >
                        <Trash2 />
                      </Button>
                    </div>
                  </>
                )}
              </div>

              <div
                className="min-h-0 flex-1 overflow-y-auto p-4"
                onScroll={(event) => {
                  const target = event.currentTarget
                  pinned.current =
                    target.scrollHeight -
                      target.scrollTop -
                      target.clientHeight <
                    48
                }}
                ref={viewport}
              >
                <div className="mx-auto flex max-w-3xl flex-col gap-4">
                  {messagesQuery.hasNextPage && (
                    <Button
                      className="self-center"
                      disabled={messagesQuery.isFetchingNextPage}
                      onClick={() => messagesQuery.fetchNextPage()}
                      size="sm"
                      variant="outline"
                    >
                      {messagesQuery.isFetchingNextPage
                        ? "Loading..."
                        : "Load older messages"}
                    </Button>
                  )}
                  {conversation.messages.map((message) => (
                    <article
                      aria-label={
                        message.kind === "proposal" ? "Proposal" : undefined
                      }
                      className={`max-w-[88%] rounded-md px-4 py-3 text-sm ${message.role === "user" ? "ml-auto bg-primary text-primary-foreground" : "bg-muted"}`}
                      key={message.id}
                    >
                      <span className="sr-only">{message.role}: </span>
                      {message.activity?.length ? (
                        <details className="mb-3 text-xs">
                          <summary>Agent activity</summary>
                          <ol className="mt-2 list-decimal pl-4">
                            {message.activity.map((part, index) => (
                              <li key={`${message.id}-${index}`}>
                                {part.text}
                              </li>
                            ))}
                          </ol>
                        </details>
                      ) : null}
                      {message.role === "assistant" ? (
                        <DevelopMarkdown>{message.content}</DevelopMarkdown>
                      ) : (
                        <div className="whitespace-pre-wrap">
                          {message.content}
                        </div>
                      )}
                      {message.kind === "proposal" && (
                        <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-3">
                          <span className="mr-auto text-xs font-medium capitalize text-muted-foreground">
                            {message.proposal_state}
                          </span>
                          <Button
                            disabled={
                              message.proposal_state !== "undecided" ||
                              conversation.running ||
                              rejectProposal.isPending
                            }
                            onClick={() => approveProposal(message.id)}
                            size="sm"
                            type="button"
                          >
                            Approve
                          </Button>
                          <Button
                            disabled={
                              message.proposal_state !== "undecided" ||
                              conversation.running ||
                              rejectProposal.isPending
                            }
                            onClick={() =>
                              selected &&
                              rejectProposal.mutate({
                                chatId: selected.id,
                                messageId: message.id,
                              })
                            }
                            size="sm"
                            type="button"
                            variant="outline"
                          >
                            Reject
                          </Button>
                        </div>
                      )}
                    </article>
                  ))}
                  {(conversation.running ||
                    conversation.response ||
                    conversation.activity.length > 0) && (
                    <article
                      aria-label="Streaming assistant response"
                      className="max-w-[88%] rounded-md bg-muted px-4 py-3 text-sm"
                    >
                      <details className="mb-3 text-xs" open>
                        <summary>
                          Agent activity ·{" "}
                          {elapsed(conversation.startedAt, now)}
                        </summary>
                        <ol className="mt-2 list-decimal pl-4 text-muted-foreground">
                          {conversation.activity.map((item, index) => (
                            <li key={`${index}-${item}`}>{item}</li>
                          ))}
                        </ol>
                      </details>
                      <DevelopMarkdown>{conversation.response}</DevelopMarkdown>
                      {conversation.error && (
                        <p className="mt-2 text-destructive">
                          {conversation.error}
                        </p>
                      )}
                    </article>
                  )}
                </div>
              </div>

              <form className="border-t p-3" onSubmit={submitExploration}>
                <div className="mx-auto flex max-w-3xl flex-wrap gap-2">
                  <Input
                    className="min-w-0 flex-1 basis-64"
                    aria-label="Exploration message"
                    disabled={
                      !workspaceQuery.data?.ready || conversation.running
                    }
                    maxLength={100000}
                    onChange={(event) => setDraft(event.target.value)}
                    placeholder={
                      workspaceQuery.data?.ready
                        ? "Explore this repository"
                        : "Set up the demo repository to explore"
                    }
                    value={draft}
                  />
                  <Button
                    disabled={
                      !workspaceQuery.data?.ready ||
                      conversation.running ||
                      propose.isPending
                    }
                    onClick={() => propose.mutate(selected.id)}
                    title="Create an implementation proposal"
                    type="button"
                    variant="outline"
                  >
                    {propose.isPending ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <Rocket />
                    )}
                    Make it happen
                  </Button>
                  {conversation.running ? (
                    <Button
                      aria-label="Stop Agent Turn"
                      disabled={stopTurn.isPending}
                      onClick={() => stopTurn.mutate(selected.id)}
                      title="Stop Agent Turn"
                      type="button"
                      variant="destructive"
                    >
                      {stopTurn.isPending ? (
                        <Loader2 className="animate-spin" />
                      ) : (
                        <Square />
                      )}
                      <span className="hidden sm:inline">Stop</span>
                    </Button>
                  ) : (
                    <Button
                      aria-label="Send exploration"
                      disabled={!workspaceQuery.data?.ready || !draft.trim()}
                      size="icon"
                      title="Send exploration"
                      type="submit"
                    >
                      <Send />
                    </Button>
                  )}
                </div>
              </form>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-6">
              <form
                className="w-full max-w-xl space-y-3"
                onSubmit={submitFirst}
              >
                <div>
                  <h2 className="text-lg font-semibold">
                    Start a Development Chat
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    Your first message creates the chat.
                  </p>
                </div>
                <div className="flex gap-2">
                  <Input
                    aria-label="First message"
                    autoFocus
                    maxLength={100000}
                    onChange={(event) => setFirstMessage(event.target.value)}
                    placeholder="What are you building?"
                    value={firstMessage}
                  />
                  <Button
                    aria-label="Send first message"
                    disabled={!firstMessage.trim() || createChat.isPending}
                    size="icon"
                    title="Send first message"
                    type="submit"
                  >
                    {createChat.isPending ? (
                      <Loader2 className="animate-spin" />
                    ) : (
                      <Send />
                    )}
                  </Button>
                </div>
              </form>
            </div>
          )}
        </section>
        <div className="hidden min-h-0 lg:block">{context}</div>
        {mobilePanel && (
          <div className="absolute inset-0 z-20 bg-background md:hidden">
            {mobilePanel === "history" ? history : context}
          </div>
        )}
      </div>

      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete Development Chat</DialogTitle>
            <DialogDescription>
              This chat, its messages, and its Development Workspace will be
              permanently deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button disabled={deleteChat.isPending} variant="outline">
                Cancel
              </Button>
            </DialogClose>
            <Button
              disabled={deleteChat.isPending || !selected}
              onClick={() => selected && deleteChat.mutate(selected)}
              variant="destructive"
            >
              Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
