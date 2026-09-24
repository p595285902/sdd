import { expect, type Page, test } from "@playwright/test"

type Chat = {
  id: string
  owner_id: string
  title: string
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
  created_at: updatedAt,
  updated_at: updatedAt,
})

const mockDevelopApi = async (page: Page) => {
  const chats = [
    createChat(chatOneId, "Most recent chat", "2026-09-24T12:00:00Z"),
    createChat(chatTwoId, "Earlier chat", "2026-09-23T12:00:00Z"),
  ]

  await page.route("**/api/v1/develop/chats**", async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const method = request.method()
    const chatMatch = url.pathname.match(/\/develop\/chats\/([^/]+)$/)
    const messagesMatch = url.pathname.match(
      /\/develop\/chats\/([^/]+)\/messages$/,
    )

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
      await route.fulfill({
        contentType: "application/json",
        json: {
          data: values.map(([suffix, content]) => ({
            id: `00000000-0000-0000-0000-00000000000${suffix}`,
            chat_id: messagesMatch[1],
            role: "user",
            content,
            created_at: `2026-09-24T12:00:0${suffix}Z`,
          })),
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
})
