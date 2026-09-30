import { createFileRoute } from "@tanstack/react-router"

import { DevelopWorkspace } from "@/features/develop/DevelopWorkspace"

export const Route = createFileRoute("/_layout/develop")({
  component: DevelopWorkspace,
  head: () => ({ meta: [{ title: "Develop - FastAPI Template" }] }),
})
