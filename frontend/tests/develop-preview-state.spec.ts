import { expect, test } from "@playwright/test"

import {
  initialPreviewAddress,
  type PreviewContext,
  type PreviewSession,
  resolvePreviewAddress,
} from "../src/features/develop/preview"

const context: PreviewContext = {
  state: "ready",
  runtime: "compose",
  initial_port: "8765",
  initial_path: "/",
  website_port: "8765",
  api_port: "8766",
}
const session: PreviewSession = {
  chat_id: "chat-one",
  credential: "credential",
  expires_in: 300,
  initial_url: "https://chat-one-8765.preview.test/",
  services: {
    initial_port: "https://chat-one-8765.preview.test",
    website_port: "https://chat-one-8765.preview.test",
    api_port: "https://chat-one-8766.preview.test",
  },
}

test("registered localhost paths retain query and fragment and route only to selected chat", () => {
  expect(
    resolvePreviewAddress(
      "localhost:8766/docs?mode=try#operation",
      initialPreviewAddress(context),
      context,
      session,
    ),
  ).toEqual({
    address: "http://localhost:8766/docs?mode=try#operation",
    src: "https://chat-one-8766.preview.test/docs?mode=try#operation",
    external: false,
  })
  expect(
    resolvePreviewAddress(
      "/details",
      initialPreviewAddress(context),
      context,
      session,
    ).src,
  ).toBe("https://chat-one-8765.preview.test/details")
  const other = {
    ...session,
    services: {
      ...session.services,
      initial_port: "https://chat-two-8765.preview.test",
    },
  }
  expect(
    resolvePreviewAddress(
      "http://localhost:8765/details",
      initialPreviewAddress(context),
      context,
      other,
    ).src,
  ).toBe("https://chat-two-8765.preview.test/details")
})

test("unregistered loopback ports never fall through to direct browser navigation", () => {
  for (const address of [
    "http://localhost:9999/",
    "http://127.0.0.1:9999/",
    "http://[::1]:9999/",
  ]) {
    expect(() =>
      resolvePreviewAddress(
        address,
        initialPreviewAddress(context),
        context,
        session,
      ),
    ).toThrow("not registered")
  }
})

test("external destinations use the browser directly", () => {
  expect(
    resolvePreviewAddress(
      "https://example.com/context-preview",
      initialPreviewAddress(context),
      context,
      session,
    ),
  ).toEqual({
    address: "https://example.com/context-preview",
    src: "https://example.com/context-preview",
    external: true,
  })
  expect(() =>
    resolvePreviewAddress(
      "https://user:secret@example.com/",
      initialPreviewAddress(context),
      context,
      session,
    ),
  ).toThrow("credentials")
  expect(() =>
    resolvePreviewAddress(
      "file:///etc/passwd",
      initialPreviewAddress(context),
      context,
      session,
    ),
  ).toThrow("HTTP")
})

test("API-only initial Swagger uses the registered initial service", () => {
  const api: PreviewContext = {
    state: "ready",
    runtime: "compose",
    initial_port: "8766",
    api_port: "8766",
    initial_path: "/docs",
  }
  const access = {
    ...session,
    services: { initial_port: "https://chat-one-8766.preview.test" },
  }
  expect(initialPreviewAddress(api)).toBe("http://localhost:8766/docs")
  expect(
    resolvePreviewAddress(
      initialPreviewAddress(api),
      initialPreviewAddress(api),
      api,
      access,
    ).src,
  ).toBe("https://chat-one-8766.preview.test/docs")
})
