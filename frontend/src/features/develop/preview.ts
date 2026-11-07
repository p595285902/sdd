export type PreviewContext = {
  state: string
  runtime?: "compose" | "unsupported"
  message?: string
  initial_port?: string
  initial_path?: string
  website_port?: string
  api_port?: string
}

export type PreviewSession = {
  chat_id: string
  credential: string
  services: Record<string, string>
  initial_url: string
  expires_in: number
}

export const initialPreviewAddress = (context: PreviewContext) =>
  `http://localhost:${context.initial_port}${context.initial_path || "/"}`

export function resolvePreviewAddress(
  input: string,
  currentAddress: string,
  context: PreviewContext,
  session: PreviewSession,
) {
  const value = input.trim()
  if (!value) throw new Error("Enter a preview address.")
  const address = new URL(
    value.startsWith("/") || /^[a-z][a-z\d+.-]*:\/\//i.test(value)
      ? value
      : `http://${value}`,
    currentAddress,
  )
  if (!["http:", "https:"].includes(address.protocol)) {
    throw new Error("Preview addresses must use HTTP or HTTPS.")
  }
  if (address.username || address.password) {
    throw new Error("Preview addresses cannot contain credentials.")
  }
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(address.hostname)
  if (!local)
    return { address: address.href, src: address.href, external: true }

  const port = address.port || (address.protocol === "https:" ? "443" : "80")
  const service = ["initial_port", "website_port", "api_port"].find(
    (key) => context[key as keyof PreviewContext] === port,
  )
  const origin = service
    ? session.services[service] ||
      (port === context.initial_port
        ? session.services.initial_port
        : undefined)
    : undefined
  if (!origin) {
    throw new Error("That localhost port is not registered for this chat.")
  }
  return {
    address: address.href,
    src: `${origin}${address.pathname}${address.search}${address.hash}`,
    external: false,
  }
}

export async function requestPreview<T>(
  chatId: string,
  action: string,
  method: "GET" | "POST",
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(
    `${import.meta.env.VITE_API_URL ?? ""}/api/v1/develop/chats/${chatId}/preview/${action}`,
    {
      method,
      signal,
      headers: {
        Authorization: `Bearer ${localStorage.getItem("access_token") ?? ""}`,
      },
    },
  )
  const body = await response.json()
  if (!response.ok) {
    throw new Error(
      body.detail || `Preview request failed (${response.status}).`,
    )
  }
  return body as T
}
