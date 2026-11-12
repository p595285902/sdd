import { expect, type Page, test } from "@playwright/test"

import type {
  PreviewExecution,
  PreviewExecutionEvent,
} from "../src/features/develop/previewExecution"

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
    executions?: PreviewExecution[]
    launchExecution?: PreviewExecution
    events?: PreviewExecutionEvent[]
    streamEvents?: PreviewExecutionEvent[]
    messages?: {
      id: string
      chat_id: string
      role: string
      content: string
      created_at: string
    }[]
  } = {},
) {
  const calls: string[] = []
  let current = options.context || contextReady
  let executions = options.executions ?? []
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
      return route.fulfill({
        json: { data: options.messages ?? [], has_more: false },
      })
    if (path.includes("/turns/current"))
      return route.fulfill({ status: 404, json: { detail: "No active turn" } })
    const action = path.split("/preview/")[1]
    if (action) {
      calls.push(`${chatId}/${action}${url.search}`)
      if (action === "executions")
        return route.fulfill({ json: { data: executions } })
      if (action.endsWith("/events")) {
        const after = Number(url.searchParams.get("after") ?? 0)
        const remaining = (options.events ?? []).filter(
          (event) => event.sequence > after,
        )
        const data = remaining.slice(0, 2)
        return route.fulfill({
          json: {
            data,
            has_more: remaining.length > data.length,
            next_sequence: data.at(-1)?.sequence ?? after,
          },
        })
      }
      if (action.endsWith("/stream")) {
        expect(route.request().headers().authorization).toBe(
          "Bearer test-token",
        )
        return route.fulfill({
          contentType: "text/event-stream",
          body: (options.streamEvents ?? [])
            .map(
              (event) =>
                `event: preview-event\ndata: ${JSON.stringify(event)}\n\n`,
            )
            .join(""),
        })
      }
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
      if (action === "launch" || action === "restart") {
        expect(route.request().postDataJSON()).toEqual({})
        if (options.launchExecution) {
          executions = [options.launchExecution]
          current = { state: "starting", runtime: "compose" }
          return route.fulfill({
            json: { ...current, execution: options.launchExecution },
          })
        }
        current = contextReady
      }
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

test("native Compose polls startup, embeds the application and retains controls", async ({
  page,
}) => {
  const calls = await mockPreview(page)
  let statusReads = 0
  await page.route("**/preview/context", (route) =>
    route.fulfill({
      json:
        ++statusReads === 1
          ? { state: "starting", runtime: "native-compose" }
          : { ...contextReady, runtime: "native-compose" },
    }),
  )
  await page.goto("/develop")
  await expect(
    preview(page).getByRole("button", { name: "Add item" }),
  ).toBeVisible()
  await expect(
    panel(page).getByRole("button", { name: "Restart preview" }),
  ).toBeVisible()
  expect(statusReads).toBeGreaterThan(1)
  await expect
    .poll(() => calls.some((call) => call.endsWith("/activity")))
    .toBe(true)
  expect(
    calls.some((call) => call.endsWith("/launch") || call.endsWith("/start")),
  ).toBe(false)
})

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

for (const width of [1440, 1024, 390, 900]) {
  test(`Context expands without losing the page or conversation controls at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    await mockPreview(page)
    await page.goto("/develop")
    if (width < 1024)
      await page
        .getByRole("button", { name: "Open development context" })
        .click()
    await expect(
      preview(page).getByRole("button", { name: "Add item" }),
    ).toBeVisible()
    await preview(page).getByRole("button", { name: "Add item" }).click()
    const frame = panel(page).locator('iframe[title="Development preview"]')
    const original = await frame.elementHandle()
    const before = await frame.boundingBox()
    expect(before).not.toBeNull()
    const expand = panel(page).getByRole("button", { name: "Expand Context" })
    await expand.focus()
    await page.keyboard.press("Enter")
    const after = await frame.boundingBox()
    expect(after).not.toBeNull()
    expect(after!.width).toBeGreaterThan(before!.width)
    expect(await original!.evaluate((element) => element.isConnected)).toBe(
      true,
    )
    await expect(preview(page).locator("output")).toHaveText("Items: 1")
    await expect(
      panel(page).getByRole("button", { name: "Collapse Context" }),
    ).toBeFocused()
    for (const control of [
      page.getByRole("textbox", { name: "Exploration message" }),
      page.getByRole("button", { name: "Send exploration" }),
      page.getByRole("combobox", { name: "Presence Mode" }),
      page.getByRole("button", { name: "Delete Development Chat" }),
    ]) {
      await expect(control).toBeVisible()
      const box = await control.boundingBox()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    }
    const conversation = await page
      .getByRole("region", { name: "Conversation" })
      .boundingBox()
    const context = await panel(page).boundingBox()
    expect(
      conversation!.x + conversation!.width <= context!.x + 1 ||
        context!.y + context!.height <= conversation!.y + 1,
    ).toBe(true)
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
    await panel(page).getByRole("button", { name: "Collapse Context" }).click()
    expect((await frame.boundingBox())!.width).toBeCloseTo(before!.width, 0)
    await expect(preview(page).locator("output")).toHaveText("Items: 1")
  })
}

test("navigation and loading notices keep the embedded viewport dimensions stable", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await mockPreview(page)
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(`${origin}/details`, async (route) => {
    await held
    await route.fulfill({ contentType: "text/html", body: "<h1>Details</h1>" })
  })
  await page.goto("/develop")
  await expect(
    preview(page).getByRole("button", { name: "Add item" }),
  ).toBeVisible()
  const frame = panel(page).locator('iframe[title="Development preview"]')
  const before = await frame.boundingBox()
  await panel(page)
    .getByRole("textbox", { name: "Preview address" })
    .fill("localhost:8765/details")
  await panel(page)
    .getByRole("textbox", { name: "Preview address" })
    .press("Enter")
  await expect(panel(page).getByRole("status")).toContainText("Loading preview")
  expect(await frame.boundingBox()).toEqual(before)
  release()
  await expect(
    preview(page).getByRole("heading", { name: "Details" }),
  ).toBeVisible()
  expect(await frame.boundingBox()).toEqual(before)
  await panel(page)
    .getByRole("textbox", { name: "Preview address" })
    .fill("https://example.com/context-preview")
  await panel(page)
    .getByRole("textbox", { name: "Preview address" })
    .press("Enter")
  await expect(
    preview(page).getByRole("heading", { name: "External page" }),
  ).toBeVisible()
  expect(await frame.boundingBox()).toEqual(before)
})

for (const width of [1440, 390]) {
  test(`visible-only activity stops on close, tab hide and chat switch at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.clock.install()
    const calls = await mockPreview(page)
    const activity = () =>
      calls.filter((call) => call === `${first}/activity`).length
    await page.goto("/develop")
    if (width < 1024) {
      await expect(
        page.getByRole("heading", { name: "First chat" }),
      ).toBeVisible()
      expect(activity()).toBe(0)
      await page
        .getByRole("button", { name: "Open development context" })
        .click()
    }
    await expect(
      preview(page).getByRole("button", { name: "Add item" }),
    ).toBeVisible()
    await expect.poll(activity).toBeGreaterThan(0)
    const initial = activity()
    await page.clock.runFor(31_000)
    await expect.poll(activity).toBeGreaterThan(initial)
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => "hidden",
      })
      document.dispatchEvent(new Event("visibilitychange"))
    })
    const hidden = activity()
    await page.clock.runFor(65_000)
    expect(activity()).toBe(hidden)
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => "visible",
      })
      document.dispatchEvent(new Event("visibilitychange"))
    })
    await expect.poll(activity).toBeGreaterThan(hidden)
    await panel(page)
      .getByRole("button", {
        name: width < 1024 ? "Close panel" : "Hide Context",
      })
      .click()
    const closed = activity()
    await expect(panel(page)).toBeHidden()
    await page.clock.runFor(65_000)
    expect(activity()).toBe(closed)
    await expect(
      page.getByRole("button", { name: "Open development context" }),
    ).toBeFocused()
    await page.getByRole("button", { name: "Open development context" }).click()
    await expect.poll(activity).toBeGreaterThan(closed)
    if (width < 768) {
      await panel(page).getByRole("button", { name: "Close panel" }).click()
      await page.getByRole("button", { name: "Open chat history" }).click()
    }
    await page
      .getByRole("navigation", { name: "Development Chats" })
      .getByRole("button", { name: "Second chat" })
      .click()
    const switched = activity()
    await page.clock.runFor(65_000)
    expect(activity()).toBe(switched)
    expect(calls.some((call) => call === `${second}/activity`)).toBe(false)
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

for (const width of [1440, 390]) {
  test(`stopped preview requires explicit Launch beside Expand at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 })
    const calls = await mockPreview(page, {
      context: { state: "stopped", runtime: "compose" },
    })
    await page.goto("/develop")
    if (width < 1024)
      await page
        .getByRole("button", { name: "Open development context" })
        .click()
    const launch = panel(page).getByRole("button", { name: "Launch preview" })
    await expect(launch).toBeEnabled()
    await expect(
      panel(page).getByRole("button", { name: "Expand Context" }),
    ).toBeVisible()
    await panel(page).getByRole("button", { name: "Expand Context" }).click()
    await panel(page).getByRole("button", { name: "Collapse Context" }).click()
    expect(calls.some((call) => /\/(start|launch|restart)$/.test(call))).toBe(
      false,
    )
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
    await launch.click()
    await expect(
      preview(page).getByRole("button", { name: "Add item" }),
    ).toBeVisible()
    expect(calls.filter((call) => call.endsWith("/launch"))).toHaveLength(1)
    await expect(launch).toBeDisabled()
  })
}

const savedExecution: PreviewExecution = {
  id: "execution-one",
  chat_id: first,
  created_at: "2026-09-24T12:01:00Z",
  updated_at: "2026-09-24T12:01:10Z",
  status: "running",
  ready: false,
  workflow: "Documented Compose watch",
  last_sequence: 4,
  truncated_bytes: 12,
}
const outputEvent = (
  sequence: number,
  kind: PreviewExecutionEvent["kind"],
  payload: PreviewExecutionEvent["payload"],
): PreviewExecutionEvent => ({
  execution_id: savedExecution.id,
  sequence,
  kind,
  payload,
  created_at: savedExecution.updated_at,
})

test("Launch remains pending beyond its HTTP response while the durable execution is starting", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const calls = await mockPreview(page, {
    context: { state: "stopped", runtime: "compose" },
    launchExecution: { ...savedExecution, status: "starting" },
    streamEvents: [outputEvent(5, "stdout", { text: "Building application…" })],
  })
  await page.goto("/develop")
  await panel(page).getByRole("button", { name: "Launch preview" }).click()
  await expect(
    page.getByRole("article", { name: "Preview execution" }),
  ).toContainText("Building application")
  await expect(
    panel(page).getByRole("button", { name: "Launching preview" }),
  ).toBeDisabled()
  await panel(page).getByRole("button", { name: "Expand Context" }).click()
  await expect(
    panel(page).getByRole("button", { name: "Launching preview" }),
  ).toBeDisabled()
  expect(calls.filter((call) => call.endsWith("/launch"))).toHaveLength(1)
})

test("safe durable operations interleave with messages, replay pages, deduplicate SSE and reattach after refresh", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const markup =
    '<img src=x onerror="window.outputExecuted=true"><script>window.outputExecuted=true</script>**literal output**'
  const events = [
    outputEvent(1, "command_start", {
      argv: ["docker", "compose", "watch"],
      cwd: "/workspace",
    }),
    outputEvent(2, "stdout", {
      text: `\u001b[31m${markup}\u001b[0m\n`,
      stream: "stdout",
    }),
    outputEvent(3, "stderr", {
      text: "Startup diagnostic\n",
      stream: "stderr",
    }),
    outputEvent(4, "output_truncated", { truncated_bytes: 12 }),
  ]
  const calls = await mockPreview(page, {
    context: { state: "stopped", runtime: "compose" },
    executions: [savedExecution],
    events,
    streamEvents: [
      events[2],
      outputEvent(5, "stdout", { text: "Fresh live output\n" }),
      outputEvent(6, "command_exit", { exit_code: 7 }),
      outputEvent(7, "status", {
        status: "failed",
        reason: "Initialization failed",
      }),
    ],
    messages: [
      {
        id: "before",
        chat_id: first,
        role: "user",
        content: "Before operation",
        created_at: "2026-09-24T12:00:00Z",
      },
      {
        id: "after",
        chat_id: first,
        role: "assistant",
        content: "After operation",
        created_at: "2026-09-24T12:02:00Z",
      },
    ],
  })
  await page.goto("/develop")
  const operation = page.getByRole("article", { name: "Preview execution" })
  await expect(operation).toContainText("Fresh live output")
  await expect(operation).toContainText("failed")
  await expect(operation.getByLabel("Preview command output")).toContainText(
    markup,
  )
  await expect(operation).toContainText("Command exited (7)")
  await expect(operation).toContainText("Output truncated: 12 bytes omitted")
  await expect(operation.locator("script, img, strong")).toHaveCount(0)
  await expect(operation.locator('[data-stream="stderr"]')).toHaveCount(1)
  expect(
    await page.evaluate(
      () => (window as Window & { outputExecuted?: boolean }).outputExecuted,
    ),
  ).toBeUndefined()
  const articles = page
    .getByRole("region", { name: "Conversation" })
    .getByRole("article")
  await expect(articles).toHaveCount(3)
  await expect(articles.nth(0)).toContainText("Before operation")
  await expect(articles.nth(1)).toHaveAttribute(
    "data-execution-id",
    savedExecution.id,
  )
  await expect(articles.nth(2)).toContainText("After operation")
  expect(calls).toContain(
    `${first}/executions/${savedExecution.id}/events?after=2`,
  )
  expect(calls).toContain(
    `${first}/executions/${savedExecution.id}/stream?after=4`,
  )
  await page.reload()
  await expect(operation).toContainText("Fresh live output")
  await expect(operation).toHaveCount(1)
  await expect(operation.locator('[data-stream="stderr"]')).toHaveCount(1)
  expect(calls.some((call) => /\/(start|launch|restart)$/.test(call))).toBe(
    false,
  )
  await operation.locator("summary").click()
  await expect(operation.getByLabel("Preview command output")).toBeHidden()
})

test("output reconnect attempts are bounded and output activity does not keep Context alive", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.clock.install()
  const calls = await mockPreview(page, {
    context: { state: "stopped", runtime: "compose" },
    executions: [savedExecution],
  })
  await page.goto("/develop")
  const streams = () =>
    calls.filter((call) => call.includes("/stream?after=")).length
  await expect.poll(streams).toBe(1)
  for (const [delay, expected] of [
    [600, 2],
    [1100, 3],
    [2100, 4],
  ]) {
    await page.clock.runFor(delay)
    await expect.poll(streams).toBe(expected)
  }
  await expect(
    page.getByRole("article", { name: "Preview execution" }).getByRole("alert"),
  ).toContainText("disconnected")
  await page.clock.runFor(30_000)
  expect(streams()).toBe(4)
  expect(calls.some((call) => call.endsWith("/activity"))).toBe(false)
  expect(calls.some((call) => /\/(start|launch|restart)$/.test(call))).toBe(
    false,
  )
})

test("saved failed output survives cleanup without an automatic replacement launch", async ({
  page,
}) => {
  const calls = await mockPreview(page, {
    context: { state: "stopped", runtime: "compose" },
    executions: [{ ...savedExecution, status: "failed", last_sequence: 2 }],
    events: [
      outputEvent(1, "command_exit", { exit_code: 1 }),
      outputEvent(2, "status", {
        status: "failed",
        reason: "Documented initialization failed",
      }),
    ],
  })
  await page.goto("/develop")
  const operation = page.getByRole("article", { name: "Preview execution" })
  await expect(operation).toBeVisible()
  await operation.locator("summary").click()
  await expect(operation).toContainText("Documented initialization failed")
  await expect(operation).toContainText("Command exited (1)")
  await expect(
    panel(page).getByRole("button", { name: "Launch preview" }),
  ).toBeEnabled()
  expect(calls.some((call) => /\/(start|launch|restart)$/.test(call))).toBe(
    false,
  )
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
    expect(
      calls.some(
        (call) => call.startsWith(second) && !call.endsWith("/executions"),
      ),
    ).toBe(false)
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
