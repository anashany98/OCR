import { describe, expect, it } from "vitest"

import { downloadUrl, pageImageUrl } from "@/api/client"

describe("downloadUrl", () => {
  it("builds a protected download endpoint", () => {
    expect(downloadUrl(42)).toContain("/documents/42/download")
  })
})

describe("pageImageUrl", () => {
  it("builds a protected OCR page preview endpoint", () => {
    expect(pageImageUrl(42, 3)).toContain("/documents/42/pages/3/image")
  })
})
