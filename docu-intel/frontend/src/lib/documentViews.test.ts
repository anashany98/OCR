import { describe, expect, it } from "vitest"

import { applyDocumentView, documentViews } from "@/lib/documentViews"

describe("documentViews", () => {
  it("exposes the professional saved views required by operations", () => {
    expect(documentViews.map((view) => view.id)).toEqual([
      "all",
      "needs-review",
      "failed",
      "plans-without-scale",
      "recent",
    ])
  })

  it("builds server-side filters for the OCR pending view", () => {
    expect(applyDocumentView("needs-review", { q: "hotel" })).toEqual({
      q: "hotel",
      status: "needs_review",
      limit: 25,
      offset: 0,
    })
  })

  it("builds server-side filters for recent documents without losing search text", () => {
    expect(applyDocumentView("recent", { q: "ABC123", limit: 50, offset: 75 })).toEqual({
      q: "ABC123",
      limit: 50,
      offset: 75,
    })
  })
})
