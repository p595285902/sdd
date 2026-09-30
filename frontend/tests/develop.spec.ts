import { expect, type Page, test } from "@playwright/test"

type Chat = {
  id: string
  owner_id: string
  title: string
  workspace_ready: boolean
  presence_mode: "stop_when_i_leave" | "continue_in_background"
  created_at: string
  updated_at: string
}

const ownerId = "00000000-0000-0000-0000-000000000001"
const chatOneId = "00000000-0000-0000-0000-000000000011"
const chatTwoId = "00000000-0000-0000-0000-000000000012"

const createChat = (id: string, title: string, updatedAt: string): Chat => ({
  id,
  owner_id: ownerId,
  title,
  workspace_ready: false,
  presence_mode: "stop_when_i_leave",
  created_at: updatedAt,
  updated_at: updatedAt,
})

const mockDevelopApi = async (
  page: Page,
  options: { waitForStop?: boolean } = {},
) => {
  const chats = [
    createChat(chatOneId, "Most recent chat", "2026-09-24T12:00:00Z"),
    createChat(chatTwoId, "Earlier chat", "2026-09-23T12:00:00Z"),
  ]
  let releaseStream: (() => void) | undefined
  const stopped = new Promise<void>((resolve) => {
    releaseStream = resolve
  })
  let proposal:
    | {
        id: string
        chat_id: string
        role: "assistant"
        content: string
        kind: "proposal"
        proposal_state: "undecided" | "approved" | "rejected"
        created_at: string
      }
    | undefined

  await page.route("**/api/v1/develop/chats**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const method = request.method()
    const chatMatch = url.pathname.match(/\/develop\/chats\/([^/]+)$/)
    const workspaceMatch = url.pathname.match(
      /\/develop\/chats\/([^/]+)\/workspace$/,
    )
    const setupMatch = url.pathname.match(
      /\/develop\/chats\/([^/]+)\/workspace\/setup$/,
    )
    const messagesMatch = url.pathname.match(
      /\/develop\/chats\/([^/]+)\/messages$/,
    )
    const proposeMatch = url.pathname.match(
      /\/develop\/chats\/([^/]+)\/messages\/propose$/,
    )
    const decisionMatch = url.pathname.match(
      /\/develop\/chats\/([^/]+)\/messages\/([^/]+)\/(reject|approve\/stream)$/,
    )
    const streamMatch = url.pathname.match(
      /\/develop\/chats\/([^/]+)\/messages\/explore\/stream$/,
    )
    const currentStreamMatch = url.pathname.match(
      /\/develop\/chats\/([^/]+)\/turns\/current\/stream$/,
    )
    const currentTurnMatch = url.pathname.match(
      /\/develop\/chats\/([^/]+)\/turns\/current$/,
    )
    const presenceMatch = url.pathname.match(
      /\/develop\/chats\/([^/]+)\/presence$/,
    )

    if (method === "POST" && streamMatch) {
      if (options.waitForStop) await stopped
      await route.fulfill({
        body: [
          'data: {"sequence":1,"kind":"status","data":"Inspecting repository"}\n\n',
          'data: {"sequence":2,"kind":"text","data":"**Repository** <img src=x onerror=alert(1)>"}\n\n',
          'data: {"sequence":3,"kind":"done","data":"complete"}\n\n',
        ].join(""),
        contentType: "text/event-stream",
      })
      return
    }

    if (method === "POST" && proposeMatch) {
      proposal = {
        id: "00000000-0000-0000-0000-000000000099",
        chat_id: proposeMatch[1],
        role: "assistant",
        content: "# Implementation proposal",
        kind: "proposal",
        proposal_state: "undecided",
        created_at: "2026-09-24T12:00:09Z",
      }
      await route.fulfill({ contentType: "application/json", json: proposal })
      return
    }

    if (method === "POST" && decisionMatch) {
      if (!proposal || proposal.id !== decisionMatch[2]) {
        throw new Error("Unexpected proposal ID")
      }
      if (decisionMatch[3] === "reject") {
        proposal.proposal_state = "rejected"
        await route.fulfill({ contentType: "application/json", json: proposal })
        return
      }
      proposal.proposal_state = "approved"
      await route.fulfill({
        body: [
          'data: {"sequence":1,"kind":"status","data":"Apply Agent Turn started"}\n\n',
          'data: {"sequence":2,"kind":"text","data":"Applied proposal"}\n\n',
          'data: {"sequence":3,"kind":"done","data":"complete"}\n\n',
        ].join(""),
        contentType: "text/event-stream",
      })
      return
    }

    if (method === "GET" && currentStreamMatch) {
      await route.fulfill({
        contentType: "application/json",
        json: { detail: "No active Agent Turn" },
        status: 404,
      })
      return
    }

    if (method === "DELETE" && currentTurnMatch) {
      releaseStream?.()
      await route.fulfill({
        contentType: "application/json",
        json: { message: "Agent Turn stopped" },
      })
      return
    }

    if (method === "PUT" && presenceMatch) {
      const chat = chats.find((entry) => entry.id === presenceMatch[1])
      const body = request.postDataJSON() as {
        presence_mode: Chat["presence_mode"]
      }
      if (!chat) throw new Error("Unexpected chat ID")
      chat.presence_mode = body.presence_mode
      await route.fulfill({ contentType: "application/json", json: chat })
      return
    }

    if (method === "POST" && setupMatch) {
      const chat = chats.find((entry) => entry.id === setupMatch[1])
      if (!chat) throw new Error("Unexpected chat ID")
      chat.workspace_ready = true
      await route.fulfill({
        contentType: "application/json",
        json: { ready: true, setup_available: true },
      })
      return
    }

    if (method === "GET" && workspaceMatch) {
      const chat = chats.find((entry) => entry.id === workspaceMatch[1])
      if (!chat) throw new Error("Unexpected chat ID")
      await route.fulfill({
        contentType: "application/json",
        json: { ready: chat.workspace_ready, setup_available: true },
      })
      return
    }

    if (method === "GET" && messagesMatch) {
      const before = url.searchParams.get("before")
      const values = before
        ? [
            ["1", "Message 1"],
            ["2", "Message 2"],
          ]
        : [
            ["3", "Message 3"],
            ["4", "Message 4"],
          ]
      const messages = values.map(([suffix, content]) => ({
        id: `00000000-0000-0000-0000-00000000000${suffix}`,
        chat_id: messagesMatch[1],
        role: "user",
        content,
        created_at: `2026-09-24T12:00:0${suffix}Z`,
      }))
      if (!before && proposal?.chat_id === messagesMatch[1]) {
        messages.push(proposal)
      }
      await route.fulfill({
        contentType: "application/json",
        json: {
          data: messages,
          has_more: !before,
          next_cursor: before ? null : "older-page",
        },
      })
      return
    }

    if (method === "PATCH" && chatMatch) {
      const chat = chats.find((entry) => entry.id === chatMatch[1])
      const body = request.postDataJSON() as { title: string }
      if (!chat) throw new Error("Unexpected chat ID")
      chat.title = body.title
      await route.fulfill({ contentType: "application/json", json: chat })
      return
    }

    if (method === "DELETE" && chatMatch) {
      if (url.searchParams.get("confirm") !== "true") {
        throw new Error("Deletion was not confirmed")
      }
      const chatIndex = chats.findIndex((entry) => entry.id === chatMatch[1])
      if (chatIndex === -1) throw new Error("Unexpected chat ID")
      chats.splice(chatIndex, 1)
      await route.fulfill({
        contentType: "application/json",
        json: { message: "Development Chat deleted" },
      })
      return
    }

    if (method === "POST" && url.pathname.endsWith("/develop/chats")) {
      const body = request.postDataJSON() as { content: string }
      const chat = createChat(
        "00000000-0000-0000-0000-000000000013",
        body.content,
        "2026-09-25T12:00:00Z",
      )
      chats.unshift(chat)
      await route.fulfill({ contentType: "application/json", json: chat })
      return
    }

    if (method === "GET" && url.pathname.endsWith("/develop/chats")) {
      await route.fulfill({
        contentType: "application/json",
        json: { data: chats, count: chats.length },
      })
      return
    }

    await route.fallback()
  })
}

test("logged-out user is redirected from Develop", async ({ browser }) => {
  const context = await browser.newContext({ storageState: undefined })
  const page = await context.newPage()

  await page.goto("/develop")

  await expect(page).toHaveURL(/\/login$/)
  await context.close()
})

test.describe("Develop chat shell", () => {
  test.beforeEach(async ({ page }) => {
    await mockDevelopApi(page)
    await page.goto("/develop")
  })

  test("shows chats in activity order and selects the latest", async ({
    page,
  }) => {
    const chatButtons = page
      .getByRole("navigation", { name: "Development Chats" })
      .getByRole("button")

    await expect(chatButtons).toHaveText(["Most recent chat", "Earlier chat"])
    await expect(
      page.getByRole("heading", { name: "Most recent chat" }),
    ).toBeVisible()
    await expect(
      page.getByRole("complementary", { name: "Development context" }),
    ).toBeVisible()
  })

  test("creates a chat from the first message", async ({ page }) => {
    await page.getByRole("button", { name: "New Development Chat" }).click()
    await page
      .getByRole("textbox", { name: "First message", exact: true })
      .fill("Create a release dashboard")
    await page.getByRole("button", { name: "Send first message" }).click()

    await expect(
      page.getByRole("heading", { name: "Create a release dashboard" }),
    ).toBeVisible()
  })

  test("renames the selected chat", async ({ page }) => {
    await page.getByRole("button", { name: "Rename Development Chat" }).click()
    await page.getByLabel("Development Chat title").fill("Renamed foundation")
    await page.getByRole("button", { name: "Save" }).click()

    await expect(
      page.getByRole("heading", { name: "Renamed foundation" }),
    ).toBeVisible()
    await expect(
      page
        .getByRole("navigation", { name: "Development Chats" })
        .getByRole("button", { name: "Renamed foundation" }),
    ).toBeVisible()
  })

  test("loads older messages in conversation order", async ({ page }) => {
    await expect(page.locator("article")).toHaveText([
      /Message 3$/,
      /Message 4$/,
    ])
    await page.getByRole("button", { name: "Load older messages" }).click()

    await expect(page.locator("article")).toHaveText([
      /Message 1$/,
      /Message 2$/,
      /Message 3$/,
      /Message 4$/,
    ])
  })

  test("sets up the selected chat demo repository", async ({ page }) => {
    await page.getByRole("button", { name: "Set up demo repository" }).click()

    await expect(
      page.getByRole("button", { name: "Demo repository ready" }),
    ).toBeDisabled()
  })

  test("streams activity and safe Markdown incrementally", async ({ page }) => {
    await page.getByRole("button", { name: "Set up demo repository" }).click()
    await page
      .getByRole("textbox", { name: "Exploration message" })
      .fill("Inspect")
    await page.getByRole("button", { name: "Send exploration" }).click()

    const response = page.getByRole("article", {
      name: "Streaming assistant response",
    })
    await expect(response.getByText("Inspecting repository")).toBeVisible()
    await expect(response.getByText("Repository", { exact: true })).toHaveCSS(
      "font-weight",
      /^(600|700)$/,
    )
    await expect(response.locator("img")).toHaveCount(0)
  })

  test("creates and loads an undecided proposal", async ({ page }) => {
    await page.getByRole("button", { name: "Set up demo repository" }).click()
    await page.getByRole("button", { name: "Make it happen" }).click()

    const proposal = page.getByRole("article", { name: "Proposal" })
    await expect(
      proposal.getByRole("heading", { name: "Implementation proposal" }),
    ).toBeVisible()
    await expect(
      proposal.getByRole("button", { name: "Approve" }),
    ).toBeEnabled()
    await expect(proposal.getByRole("button", { name: "Reject" })).toBeEnabled()
  })

  test("streams approval and disables persisted decisions", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "Set up demo repository" }).click()
    await page.getByRole("button", { name: "Make it happen" }).click()
    await page.getByRole("button", { name: "Approve" }).click()

    await expect(page.getByText("Applied proposal")).toBeVisible()
    const proposal = page.getByRole("article", { name: "Proposal" })
    await expect(proposal.getByText("approved", { exact: true })).toBeVisible()
    await expect(
      proposal.getByRole("button", { name: "Approve" }),
    ).toBeDisabled()
    await expect(
      proposal.getByRole("button", { name: "Reject" }),
    ).toBeDisabled()
  })

  test("rejects a proposal without starting an apply stream", async ({
    page,
  }) => {
    await page.getByRole("button", { name: "Set up demo repository" }).click()
    await page.getByRole("button", { name: "Make it happen" }).click()
    await page.getByRole("button", { name: "Reject" }).click()

    const proposal = page.getByRole("article", { name: "Proposal" })
    await expect(proposal.getByText("rejected", { exact: true })).toBeVisible()
    await expect(
      proposal.getByRole("button", { name: "Approve" }),
    ).toBeDisabled()
    await expect(
      page.getByRole("article", { name: "Streaming assistant response" }),
    ).toHaveCount(0)
  })

  test("updates Presence Mode with explicit labels", async ({ page }) => {
    const continueButton = page.getByRole("button", {
      name: "Continue in background",
    })
    await continueButton.click()
    await expect(continueButton).toHaveAttribute("aria-pressed", "true")
  })

  test("stops a running Agent Turn", async ({ page }) => {
    await mockDevelopApi(page, { waitForStop: true })
    await page.reload()
    await page.getByRole("button", { name: "Set up demo repository" }).click()
    await page
      .getByRole("textbox", { name: "Exploration message" })
      .fill("Wait")
    await page.getByRole("button", { name: "Send exploration" }).click()

    await page.getByRole("button", { name: "Stop Agent Turn" }).click()
    await expect(
      page.getByRole("button", { name: "Send exploration" }),
    ).toBeVisible()
  })

  test("uses explicit history and context controls on narrow screens", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload()

    await expect(
      page.getByRole("navigation", { name: "Development Chats" }),
    ).not.toBeVisible()
    await page.getByRole("button", { name: "Open chat history" }).click()
    await expect(
      page.getByRole("navigation", { name: "Development Chats" }),
    ).toBeVisible()
    await page.getByRole("button", { name: "Close panel" }).click()
    await page.getByRole("button", { name: "Open development context" }).click()
    await expect(
      page.getByRole("complementary", { name: "Development context" }),
    ).toBeVisible()
  })

  test("cancels Development Chat deletion", async ({ page }) => {
    await page.getByRole("button", { name: "Delete Development Chat" }).click()
    await expect(
      page.getByRole("dialog", { name: "Delete Development Chat" }),
    ).toBeVisible()

    await page.getByRole("button", { name: "Cancel" }).click()

    await expect(
      page.getByRole("heading", { name: "Most recent chat" }),
    ).toBeVisible()
  })

  test("permanently deletes a Development Chat", async ({ page }) => {
    await page.getByRole("button", { name: "Delete Development Chat" }).click()
    await page.getByRole("button", { name: "Delete permanently" }).click()

    await expect(
      page.getByRole("heading", { name: "Earlier chat" }),
    ).toBeVisible()
    await expect(
      page
        .getByRole("navigation", { name: "Development Chats" })
        .getByRole("button", { name: "Most recent chat" }),
    ).not.toBeVisible()
  })
})
