import { useQuery } from "@tanstack/react-query"
import { Loader2, RotateCcw, RotateCw } from "lucide-react"
import { type FormEvent, useEffect, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import {
  hasPreviewRuntime,
  initialPreviewAddress,
  type PreviewContext,
  type PreviewSession,
  requestPreview,
  resolvePreviewAddress,
} from "./preview"
import type { PreviewControls } from "./usePreviewExecution"

function PreviewBrowser({
  chatId,
  context,
  session,
}: {
  chatId: string
  context: PreviewContext
  session: PreviewSession
}) {
  const initialAddress = initialPreviewAddress(context)
  const [address, setAddress] = useState(initialAddress)
  const [destination, setDestination] = useState(() =>
    resolvePreviewAddress(initialAddress, initialAddress, context, session),
  )
  const [authorized, setAuthorized] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [reload, setReload] = useState(0)
  const form = useRef<HTMLFormElement>(null)
  const bootstrap = useRef<HTMLIFrameElement>(null)
  const submittedCredential = useRef("")
  const frameName = `preview-authorization-${chatId}`

  useEffect(() => {
    if (submittedCredential.current === session.credential) return
    submittedCredential.current = session.credential
    form.current?.submit()
  }, [session.credential])

  const navigate = (event?: FormEvent) => {
    event?.preventDefault()
    try {
      const next = resolvePreviewAddress(
        address,
        destination.address,
        context,
        session,
      )
      setDestination(next)
      setAddress(next.address)
      setError("")
      setLoading(true)
      setReload((value) => value + 1)
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Invalid preview address.",
      )
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <form
        aria-label="Preview navigation"
        className="border-b p-2"
        onSubmit={navigate}
      >
        <Input
          aria-label="Preview address"
          autoComplete="off"
          className="min-w-0 text-xs"
          disabled={!authorized}
          onChange={(event) => setAddress(event.target.value)}
          value={address}
        />
        <div className="mt-2 flex gap-2">
          <Button
            disabled={!authorized}
            size="sm"
            type="submit"
            variant="outline"
          >
            Go
          </Button>
          <Button
            aria-label="Reload preview"
            disabled={!authorized}
            onClick={() => {
              setError("")
              setLoading(true)
              setReload((value) => value + 1)
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            <RotateCw /> Reload
          </Button>
        </div>
      </form>
      {/* A form navigation, unlike cross-origin fetch, can exchange the short-lived
          credential for an HttpOnly service cookie without putting it in a URL. */}
      <form
        action={`${session.services.initial_port}/session`}
        method="post"
        ref={form}
        target={frameName}
        hidden
      >
        <input name="credential" type="hidden" value={session.credential} />
      </form>
      <iframe
        hidden
        key={session.credential}
        name={frameName}
        onLoad={() => {
          try {
            if (
              bootstrap.current?.contentWindow?.location.href === "about:blank"
            )
              return
          } catch {
            // The exchanged page is on the separate preview origin.
          }
          setAuthorized(true)
        }}
        ref={bootstrap}
        title="Preview authorization"
      />
      <div className="relative min-h-80 flex-1">
        {authorized && (
          <iframe
            className="absolute inset-0 h-full w-full border-0 bg-white"
            key={reload}
            onError={() => {
              setLoading(false)
              setError("Unable to load this preview address.")
            }}
            onLoad={() => setLoading(false)}
            src={destination.src}
            title="Development preview"
          />
        )}
        <div className="pointer-events-none absolute inset-x-0 top-0">
          {error && (
            <p
              className="bg-background/95 p-2 text-xs text-destructive"
              role="alert"
            >
              {error}
            </p>
          )}
          {loading && (
            <p
              className="flex items-center gap-2 bg-background/95 p-2 text-xs text-muted-foreground"
              role="status"
            >
              <Loader2 className="size-3 animate-spin" /> Loading preview…
            </p>
          )}
          {destination.external && (
            <p className="bg-background/95 p-2 text-xs text-muted-foreground">
              External pages load directly. Some sites do not allow embedding.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

export function DevelopPreview({
  chatId,
  workspaceReady,
  setupPending,
  open,
  controls,
}: {
  chatId: string
  workspaceReady: boolean
  setupPending: boolean
  open: boolean
  controls: PreviewControls
}) {
  const active = open
  const { contextQuery, actionPending, actionError, sessionGeneration } =
    controls
  const context = contextQuery.data
  const sessionKey = ["development-preview-session", chatId, sessionGeneration]

  const ready =
    active &&
    workspaceReady &&
    !setupPending &&
    hasPreviewRuntime(context) &&
    context?.state === "ready" &&
    !actionPending &&
    !actionError
  const sessionQuery = useQuery({
    queryKey: sessionKey,
    enabled: ready,
    gcTime: 0,
    retry: false,
    queryFn: async ({ signal }) => {
      const session = await requestPreview<PreviewSession>(
        chatId,
        "browser-session",
        "POST",
        signal,
      )
      if (
        session.chat_id !== chatId ||
        !session.services.initial_port ||
        !session.credential
      ) {
        throw new Error("Invalid browser session for the selected chat.")
      }
      return session
    },
    refetchInterval: ready ? 240_000 : false,
  })

  useEffect(() => {
    if (!ready) return
    let timer: number | undefined
    let pending: AbortController | null = null
    const heartbeat = () => {
      if (document.visibilityState !== "visible" || pending) return
      const controller = new AbortController()
      pending = controller
      void requestPreview(chatId, "activity", "POST", controller.signal)
        .catch(() => undefined)
        .finally(() => {
          if (pending === controller) pending = null
        })
    }
    const stopHeartbeat = () => {
      window.clearInterval(timer)
      pending?.abort()
      pending = null
    }
    const syncVisibility = () => {
      stopHeartbeat()
      if (document.visibilityState === "visible") {
        heartbeat()
        timer = window.setInterval(heartbeat, 30_000)
      }
    }
    syncVisibility()
    document.addEventListener("visibilitychange", syncVisibility)
    return () => {
      document.removeEventListener("visibilitychange", syncVisibility)
      stopHeartbeat()
    }
  }, [ready, chatId])

  const error = actionError || contextQuery.error || sessionQuery.error
  const pending =
    setupPending ||
    (active && workspaceReady && contextQuery.isPending) ||
    controls.starting
  let status = "Set up the repository to preview this chat."
  if (pending)
    status = setupPending
      ? "Setting up the repository…"
      : "Starting Compose preview…"
  else if (error) status = error.message
  else if (context?.message) status = context.message
  else if (context?.state === "failed")
    status =
      "Compose preview failed. Check the checkout's startup instructions and try Restart."
  else if (context?.state === "stopped")
    status = "Compose preview is stopped. Select Launch to start it."
  else if (ready) status = "Authorizing preview…"

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {hasPreviewRuntime(context) && (
        <div className="border-b p-2">
          <Button
            aria-label="Restart preview"
            disabled={actionPending || !active || !workspaceReady}
            onClick={controls.restart}
            size="sm"
            variant="outline"
          >
            <RotateCcw /> Restart
          </Button>
        </div>
      )}
      {ready && sessionQuery.data && !error ? (
        <PreviewBrowser
          chatId={chatId}
          context={context}
          session={sessionQuery.data}
        />
      ) : (
        <p
          className="flex items-start gap-2 p-4 text-sm text-muted-foreground"
          role={error || context?.state === "failed" ? "alert" : "status"}
        >
          {pending && (
            <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin" />
          )}
          {status}
        </p>
      )}
    </div>
  )
}
