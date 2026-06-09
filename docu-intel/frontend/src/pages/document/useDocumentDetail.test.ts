import { describe, expect, it } from "vitest"

import {
  entityLabel,
  filterPages,
  hasThumbnailExt,
  isKeyEntity,
  shortHash,
} from "./useDocumentDetail"

describe("isKeyEntity", () => {
  it("returns true for known entity types", () => {
    expect(isKeyEntity("invoice_number")).toBe(true)
    expect(isKeyEntity("supplier")).toBe(true)
    expect(isKeyEntity("total_amount")).toBe(true)
  })

  it("accepts case-insensitive variants", () => {
    expect(isKeyEntity("INVOICE_NUMBER")).toBe(true)
    expect(isKeyEntity("Client")).toBe(true)
  })

  it("returns false for unknown entity types", () => {
    expect(isKeyEntity("random_field")).toBe(false)
    expect(isKeyEntity("")).toBe(false)
  })
})

describe("entityLabel", () => {
  it("returns a human label for known types", () => {
    expect(entityLabel("invoice_number")).toBe("Nº Factura")
    expect(entityLabel("total_amount")).toBe("Importe total")
  })

  it("falls back to a humanised identifier for unknown types", () => {
    expect(entityLabel("line_count")).toBe("line count")
    expect(entityLabel("my_custom_field")).toBe("my custom field")
  })
})

describe("filterPages", () => {
  const pages = [
    { id: 1, page_number: 1, text: "Factura de proveedor ACME" } as never,
    { id: 2, page_number: 2, text: "Pedido n\u00famero 1234" } as never,
    { id: 3, page_number: 3, text: null } as never,
  ]

  it("returns all pages when the query is empty", () => {
    expect(filterPages(pages, "").map((p) => p.id)).toEqual([1, 2, 3])
  })

  it("matches case-insensitively", () => {
    expect(filterPages(pages, "ACME").map((p) => p.id)).toEqual([1])
    expect(filterPages(pages, "pedido").map((p) => p.id)).toEqual([2])
  })

  it("skips pages with no text", () => {
    expect(filterPages(pages, "factura").map((p) => p.id)).toEqual([1])
  })

  it("returns an empty array when nothing matches", () => {
    expect(filterPages(pages, "xyz")).toEqual([])
  })
})

describe("shortHash", () => {
  it("returns a 10+3+6 dash format for a 64-char SHA256", () => {
    const h = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    expect(shortHash(h)).toBe("0123456789...abcdef")
  })

  it("returns the dash placeholder for empty/null values", () => {
    expect(shortHash(null)).toBe("\u2014")
    expect(shortHash(undefined)).toBe("\u2014")
    expect(shortHash("")).toBe("\u2014")
  })
})

describe("hasThumbnailExt", () => {
  it("accepts the image extensions that have a thumbnail fallback", () => {
    expect(hasThumbnailExt(".png")).toBe(true)
    expect(hasThumbnailExt(".JPG")).toBe(true)
    expect(hasThumbnailExt(".webp")).toBe(true)
  })

  it("rejects non-image extensions", () => {
    expect(hasThumbnailExt(".pdf")).toBe(false)
    expect(hasThumbnailExt(".xlsx")).toBe(false)
    expect(hasThumbnailExt(null)).toBe(false)
    expect(hasThumbnailExt(undefined)).toBe(false)
  })
})
