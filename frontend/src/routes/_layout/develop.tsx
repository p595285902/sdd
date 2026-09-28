import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import {
  GitBranch,
  Loader2,
  MessageSquarePlus,
  Pencil,
  Send,
  Trash2,
} from "lucide-react"
import { type FormEvent, useState } from "react"

import { type DevelopmentChatPublic, DevelopService } from "@/client"
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

export const Route = createFileRoute("/_layout/develop")({
  component: Develop,
  head: () => ({
    meta: [
      {
        title: "Develop - FastAPI Template",
      },
    ],
  }),
})

function Develop() {
  const queryClient = useQueryClient()
  const { showErrorToast } = useCustomToast()
  const [selectedChatId, setSelectedChatId] = useState<string | "new" | null>(
    null,
  )
  const [firstMessage, setFirstMessage] = useState("")
  const [isRenaming, setIsRenaming] = useState(false)
  const [renameTitle, setRenameTitle] = useState("")
  const [isDeleteOpen, setIsDeleteOpen] = useState(false)

  const chatsQuery = useQuery({
    queryFn: async () => (await DevelopService.readDevelopmentChats()).data,
    queryKey: ["development-chats"],
  })
  const chats = chatsQuery.data?.data ?? []
  const effectiveChatId =
    selectedChatId === null ? chats[0]?.id : selectedChatId
  const selectedChat =
    effectiveChatId === "new"
      ? undefined
      : chats.find((chat) => chat.id === effectiveChatId)

  const workspaceQuery = useQuery({
    enabled: Boolean(selectedChat),
    queryFn: async () =>
      (
        await DevelopService.readDevelopmentWorkspace({
          path: { chat_id: selectedChat?.id ?? "" },
        })
      ).data,
    queryKey: ["development-workspace", selectedChat?.id],
  })

  const messagesQuery = useInfiniteQuery({
    enabled: Boolean(selectedChat),
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) =>
      (
        await DevelopService.readDevelopmentMessages({
          path: { chat_id: selectedChat?.id ?? "" },
          query: pageParam ? { before: pageParam } : {},
        })
      ).data,
    queryKey: ["development-messages", selectedChat?.id],
    getNextPageParam: (page) =>
      page.has_more ? (page.next_cursor ?? undefined) : undefined,
  })
  const messages =
    messagesQuery.data?.pages
      .slice()
      .reverse()
      .flatMap((page) => page.data) ?? []

  const createChat = useMutation({
    mutationFn: async (content: string) =>
      (await DevelopService.createDevelopmentChat({ body: { content } })).data,
    onError: handleError.bind(showErrorToast),
    onSuccess: async (chat) => {
      setFirstMessage("")
      setSelectedChatId(chat.id)
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
          body: { title },
          path: { chat_id: chat.id },
        })
      ).data,
    onError: handleError.bind(showErrorToast),
    onSuccess: async () => {
      setIsRenaming(false)
      await queryClient.invalidateQueries({ queryKey: ["development-chats"] })
    },
  })

  const setupWorkspace = useMutation({
    mutationFn: async (chat: DevelopmentChatPublic) =>
      (
        await DevelopService.setupDevelopmentWorkspace({
          path: { chat_id: chat.id },
        })
      ).data,
    onError: handleError.bind(showErrorToast),
    onSuccess: async (workspace) => {
      queryClient.setQueryData(
        ["development-workspace", selectedChat?.id],
        workspace,
      )
      await queryClient.invalidateQueries({ queryKey: ["development-chats"] })
    },
  })

  const deleteChat = useMutation({
    mutationFn: async (chat: DevelopmentChatPublic) =>
      DevelopService.deleteDevelopmentChat({
        path: { chat_id: chat.id },
        query: { confirm: true },
      }),
    onError: handleError.bind(showErrorToast),
    onSuccess: async () => {
      setIsDeleteOpen(false)
      setSelectedChatId(null)
      await queryClient.invalidateQueries({ queryKey: ["development-chats"] })
    },
  })

  const handleCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const content = firstMessage.trim()
    if (content) createChat.mutate(content)
  }

  const handleRename = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const title = renameTitle.trim()
    if (selectedChat && title) renameChat.mutate({ chat: selectedChat, title })
  }

  const startRename = () => {
    if (!selectedChat) return
    setRenameTitle(selectedChat.title)
    setIsRenaming(true)
  }

  return (
    <div className="flex min-h-[calc(100vh-12rem)] flex-col gap-5">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Develop</h1>
        <p className="text-muted-foreground">Development Chats</p>
      </header>

      <div className="grid min-h-0 flex-1 overflow-hidden border md:grid-cols-[17rem_minmax(0,1fr)]">
        <aside className="flex min-h-56 flex-col border-b bg-muted/20 md:border-r md:border-b-0">
          <div className="flex items-center justify-between border-b px-3 py-3">
            <h2 className="text-sm font-semibold">Recent chats</h2>
            <Button
              aria-label="New Development Chat"
              onClick={() => setSelectedChatId("new")}
              size="icon-sm"
              title="New Development Chat"
              variant="ghost"
            >
              <MessageSquarePlus />
            </Button>
          </div>
          <nav
            aria-label="Development Chats"
            className="min-h-0 overflow-y-auto p-2"
          >
            {chatsQuery.isPending ? (
              <div className="flex justify-center py-8 text-muted-foreground">
                <Loader2 className="animate-spin" aria-label="Loading chats" />
              </div>
            ) : chats.length === 0 ? (
              <p className="px-2 py-6 text-center text-sm text-muted-foreground">
                No chats yet
              </p>
            ) : (
              <div className="space-y-1">
                {chats.map((chat) => (
                  <button
                    className={`w-full truncate rounded-sm px-3 py-2 text-left text-sm transition-colors ${
                      selectedChat?.id === chat.id
                        ? "bg-accent font-medium text-accent-foreground"
                        : "hover:bg-accent/60"
                    }`}
                    key={chat.id}
                    onClick={() => {
                      setSelectedChatId(chat.id)
                      setIsRenaming(false)
                    }}
                    type="button"
                  >
                    {chat.title}
                  </button>
                ))}
              </div>
            )}
          </nav>
        </aside>

        <section
          className="flex min-h-[30rem] min-w-0 flex-col"
          aria-label="Conversation"
        >
          {selectedChat ? (
            <>
              <div className="flex min-h-14 items-center justify-between border-b px-4 py-2">
                {isRenaming ? (
                  <form className="flex w-full gap-2" onSubmit={handleRename}>
                    <Input
                      aria-label="Development Chat title"
                      autoFocus
                      maxLength={255}
                      onChange={(event) => setRenameTitle(event.target.value)}
                      value={renameTitle}
                    />
                    <Button
                      disabled={!renameTitle.trim() || renameChat.isPending}
                      type="submit"
                    >
                      Save
                    </Button>
                    <Button
                      onClick={() => setIsRenaming(false)}
                      type="button"
                      variant="ghost"
                    >
                      Cancel
                    </Button>
                  </form>
                ) : (
                  <>
                    <h2 className="truncate text-base font-semibold">
                      {selectedChat.title}
                    </h2>
                    <div className="flex shrink-0 items-center gap-1">
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
                        onClick={() => setupWorkspace.mutate(selectedChat)}
                        size="sm"
                        title={
                          workspaceQuery.data?.ready
                            ? "Demo repository ready"
                            : "Set up demo repository"
                        }
                        variant="outline"
                      >
                        {setupWorkspace.isPending ? (
                          <Loader2 className="animate-spin" />
                        ) : (
                          <GitBranch />
                        )}
                        <span className="hidden sm:inline">
                          {workspaceQuery.data?.ready
                            ? "Demo repository ready"
                            : "Set up demo repository"}
                        </span>
                      </Button>
                      <Button
                        aria-label="Rename Development Chat"
                        onClick={startRename}
                        size="icon-sm"
                        title="Rename Development Chat"
                        variant="ghost"
                      >
                        <Pencil />
                      </Button>
                      <Button
                        aria-label="Delete Development Chat"
                        onClick={() => setIsDeleteOpen(true)}
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

              <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
                {messagesQuery.isPending ? (
                  <div className="flex flex-1 items-center justify-center text-muted-foreground">
                    <Loader2
                      className="animate-spin"
                      aria-label="Loading messages"
                    />
                  </div>
                ) : (
                  <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
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
                    {messages.map((message) => (
                      <article
                        className={`max-w-[85%] whitespace-pre-wrap rounded-md px-4 py-3 text-sm ${
                          message.role === "user"
                            ? "ml-auto bg-primary text-primary-foreground"
                            : "bg-muted"
                        }`}
                        key={message.id}
                      >
                        <span className="sr-only">{message.role}: </span>
                        {message.content}
                      </article>
                    ))}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center p-6">
              <form
                className="w-full max-w-xl space-y-3"
                onSubmit={handleCreate}
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
      </div>

      <Dialog open={isDeleteOpen} onOpenChange={setIsDeleteOpen}>
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
              disabled={deleteChat.isPending || !selectedChat}
              onClick={() => selectedChat && deleteChat.mutate(selectedChat)}
              variant="destructive"
            >
              {deleteChat.isPending && <Loader2 className="animate-spin" />}
              Delete permanently
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
