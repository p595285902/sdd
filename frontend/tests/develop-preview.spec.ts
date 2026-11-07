import { expect, type Page, test } from "@playwright/test"

const first = "00000000-0000-0000-0000-000000000011"
const second = "00000000-0000-0000-0000-000000000012"
const origin = `https://${first}-8765.preview.test`
const contextReady = {
  state: "ready",
  runtime: "compose",
  initial_port: "8765",
  initial_path: "/",
  website_port: "8765",
}

test.use({ storageState: { cookies: [], origins: [] } })

async function mockPreview(
  page: Page,
  options: {
    context?: Record<string, string>
    delayContext?: Promise<void>
    delaySession?: Promise<void>
    delayRestart?: Promise<void>
  } = {},
) {
  const calls: string[] = []
  let current = options.context || contextReady
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "test-token"),
  )
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        id: first,
        email: "user@example.com",
        is_active: true,
        is_superuser: false,
      },
    }),
  )
  await page.route("**/api/v1/develop/chats**", async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const chatId = path.includes(second) ? second : first
    if (path.endsWith("/chats")) {
      return route.fulfill({
        json: {
          data: [first, second].map((id, index) => ({
            id,
            owner_id: first,
            title: index ? "Second chat" : "First chat",
            workspace_ready: !index,
            presence_mode: "stop_when_i_leave",
            created_at: "2026-09-24T12:00:00Z",
            updated_at: "2026-09-24T12:00:00Z",
          })),
          count: 2,
        },
      })
    }
    if (path.endsWith("/workspace"))
      return route.fulfill({ json: { ready: chatId === first } })
    if (path.endsWith("/messages"))
      return route.fulfill({ json: { data: [], has_more: false } })
    if (path.includes("/turns/current"))
      return route.fulfill({ status: 404, json: { detail: "No active turn" } })
    const action = path.split("/preview/")[1]
    if (action) {
      calls.push(`${chatId}/${action}`)
      if (action === "context") {
        await options.delayContext
        return route.fulfill({ json: current }).catch(() => undefined)
      }
      if (action === "browser-session") {
        await options.delaySession
        return route
          .fulfill({
            json: {
              chat_id: chatId,
              credential: "test-credential",
              expires_in: 300,
              services: { initial_port: origin, website_port: origin },
              initial_url: `${origin}/`,
            },
          })
          .catch(() => undefined)
      }
      if (action === "restart") await options.delayRestart
      if (action === "start" || action === "restart") current = contextReady
      return route.fulfill({ json: { state: "ready" } })
    }
    return route.fulfill({ json: {} })
  })
  await page.route(`${origin}/**`, async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === "/session") {
      expect(route.request().method()).toBe("POST")
      expect(route.request().postData()).toBe("credential=test-credential")
      return route.fulfill({ contentType: "text/html", body: "Authorized" })
    }
    if (path === "/docs/")
      return route.fulfill({
        contentType: "text/html",
        body: '<h1>Swagger</h1><output></output><script>document.querySelector("output").textContent="OpenAPI loaded"</script>',
      })
    return route.fulfill({
      contentType: "text/html",
      body:
        path === "/details"
          ? "<h1>Details</h1>"
          : "<button onclick=\"document.querySelector('output').textContent='Items: 1'\">Add item</button><output>Items: 0</output><a href=\"/details\">Open details</a>",
    })
  })
  await page.route("https://example.com/context-preview", (route) =>
    route.fulfill({ contentType: "text/html", body: "<h1>External page</h1>" }),
  )
  return calls
}

const panel = (page: Page) =>
  page.getByRole("complementary", { name: "Development context" })
const preview = (page: Page) =>
  page.frameLocator('iframe[title="Development preview"]')

for (const width of [1440, 390, 900]) {
  test(`interactive Compose preview, address, reload and direct external navigation at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const calls = await mockPreview(page)
    await page.goto("/develop")
    if (width < 1024) {
      await expect(
        page.getByRole("button", { name: "Open development context" }),
      ).toBeVisible()
      expect(calls.some((call) => call.endsWith("/start"))).toBe(false)
      await page
        .getByRole("button", { name: "Open development context" })
        .click()
    }
    await expect(
      preview(page).getByRole("button", { name: "Add item" }),
    ).toBeVisible()
    await preview(page).getByRole("button", { name: "Add item" }).click()
    await expect(preview(page).locator("output")).toHaveText("Items: 1")
    await panel(page).getByRole("button", { name: "Reload preview" }).click()
    await expect(preview(page).locator("output")).toHaveText("Items: 0")
    await panel(page)
      .getByRole("textbox", { name: "Preview address" })
      .fill("localhost:8765/details")
    await panel(page)
      .getByRole("textbox", { name: "Preview address" })
      .press("Enter")
    await expect(
      preview(page).getByRole("heading", { name: "Details" }),
    ).toBeVisible()
    await expect(
      panel(page).getByRole("textbox", { name: "Preview address" }),
    ).toHaveValue("http://localhost:8765/details")
    await panel(page)
      .getByRole("textbox", { name: "Preview address" })
      .fill("https://example.com/context-preview")
    await panel(page)
      .getByRole("textbox", { name: "Preview address" })
      .press("Enter")
    await expect(
      preview(page).getByRole("heading", { name: "External page" }),
    ).toBeVisible()
    await expect(
      panel(page).locator('iframe[title="Development preview"]'),
    ).toHaveAttribute("src", "https://example.com/context-preview")
    await expect(
      panel(page).getByRole("button", { name: /Back|Forward/ }),
    ).toHaveCount(0)
    await expect(
      panel(page).locator('iframe[title="Development preview"]'),
    ).toHaveCount(1)
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true)
  })
}

test("API-only Swagger is the initial requested page and runs scripts", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockPreview(page, {
    context: {
      state: "ready",
      runtime: "compose",
      initial_port: "8765",
      api_port: "8765",
      initial_path: "/docs/",
    },
  })
  await page.goto("/develop")
  await expect(
    preview(page).getByRole("heading", { name: "Swagger" }),
  ).toBeVisible()
  await expect(preview(page).locator("output")).toHaveText("OpenAPI loaded")
  await expect(
    panel(page).getByRole("textbox", { name: "Preview address" }),
  ).toHaveValue("http://localhost:8765/docs/")
})

test("a stopped Compose preview starts only on first visible Context visit", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 900 })
  const calls = await mockPreview(page, {
    context: { state: "stopped", runtime: "compose" },
  })
  await page.goto("/develop")
  await expect(page.getByRole("heading", { name: "First chat" })).toBeVisible()
  expect(calls.some((call) => call.endsWith("/start"))).toBe(false)
  await page.getByRole("button", { name: "Open development context" }).click()
  await expect(
    preview(page).getByRole("button", { name: "Add item" }),
  ).toBeVisible()
  expect(calls.filter((call) => call.endsWith("/start"))).toHaveLength(1)
})

test("Compose failures show an error instead of a stale page", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockPreview(page, {
    context: {
      state: "failed",
      runtime: "compose",
      message: "Compose configuration is unsafe.",
    },
  })
  await page.goto("/develop")
  await expect(panel(page).getByRole("alert")).toHaveText(
    "Compose configuration is unsafe.",
  )
  await expect(panel(page).locator("iframe")).toHaveCount(0)
  await expect(
    panel(page).getByRole("button", { name: "Restart preview" }),
  ).toBeEnabled()
})

test("non-Compose instructions never start or authorize a preview", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const calls = await mockPreview(page, {
    context: {
      state: "needs_instructions",
      runtime: "unsupported",
      message: "Compose startup instructions are required.",
    },
  })
  await page.goto("/develop")
  await expect(panel(page)).toContainText(
    "Compose startup instructions are required",
  )
  expect(
    calls.some((call) => /\/(start|restart|browser-session)$/.test(call)),
  ).toBe(false)
  await expect(panel(page).locator("iframe")).toHaveCount(0)
})

test("checkout conversion never displays or restarts an existing non-Compose runtime", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const calls = await mockPreview(page, {
    context: {
      state: "unsupported",
      runtime: "unsupported",
      message:
        "This checkout has an existing non-Compose runtime. Context only supports Compose previews; this runtime has not been restarted.",
    },
  })
  await page.goto("/develop")
  await expect(panel(page)).toContainText("existing non-Compose runtime")
  await expect(panel(page).locator("iframe")).toHaveCount(0)
  await expect(
    panel(page).getByRole("button", { name: "Restart preview" }),
  ).toHaveCount(0)
  expect(
    calls.some((call) => /\/(start|restart|browser-session)$/.test(call)),
  ).toBe(false)
})

for (const phase of ["context", "session"] as const) {
  test(`chat switch discards a delayed ${phase} response`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    let release!: () => void
    const delayed = new Promise<void>((resolve) => {
      release = resolve
    })
    const calls = await mockPreview(
      page,
      phase === "context"
        ? { delayContext: delayed }
        : { delaySession: delayed },
    )
    await page.goto("/develop")
    await expect
      .poll(() =>
        calls.some((call) =>
          call.endsWith(phase === "context" ? "/context" : "/browser-session"),
        ),
      )
      .toBe(true)
    await page
      .getByRole("navigation", { name: "Development Chats" })
      .getByRole("button", { name: "Second chat" })
      .click()
    release()
    await expect(panel(page)).toContainText("Set up the repository")
    await expect(panel(page).locator("iframe")).toHaveCount(0)
    expect(calls.some((call) => call.startsWith(second))).toBe(false)
  })
}

test("Restart removes the old page and shows startup until ready", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  let release!: () => void
  const delayed = new Promise<void>((resolve) => {
    release = resolve
  })
  const calls = await mockPreview(page, { delayRestart: delayed })
  await page.goto("/develop")
  await expect(
    preview(page).getByRole("button", { name: "Add item" }),
  ).toBeVisible()
  await panel(page).getByRole("button", { name: "Restart preview" }).click()
  await expect(panel(page)).toContainText("Starting Compose preview")
  await expect(
    panel(page).locator('iframe[title="Development preview"]'),
  ).toHaveCount(0)
  release()
  await expect(
    preview(page).getByRole("button", { name: "Add item" }),
  ).toBeVisible()
  expect(
    calls.filter((call) => call.endsWith("/browser-session")),
  ).toHaveLength(2)
})
