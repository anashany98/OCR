import { describe, expect, it } from "vitest"

import { colorForSymbolClass, filterSymbolsByPage, humaniseSymbolClass } from "./usePlanSymbols"
import type { PlanSymbol } from "@/api/plans"

// ---------------------------------------------------------------------------
// filterSymbolsByPage
// ---------------------------------------------------------------------------

function makeSymbol(overrides: Partial<PlanSymbol> = {}): PlanSymbol {
  return {
    id: 1,
    plan_id: 1,
    symbol_class: "door",
    confidence: 0.9,
    page_number: 1,
    bbox_x1: 0,
    bbox_y1: 0,
    bbox_x2: 10,
    bbox_y2: 10,
    source_model: "test",
    ...overrides,
  }
}

describe("filterSymbolsByPage", () => {
  it("keeps only symbols matching the requested page", () => {
    const syms = [
      makeSymbol({ id: 1, page_number: 1 }),
      makeSymbol({ id: 2, page_number: 2 }),
      makeSymbol({ id: 3, page_number: 3 }),
    ]
    expect(filterSymbolsByPage(syms, 2).map((s) => s.id)).toEqual([2])
  })

  it("keeps symbols with null page_number (single-page plans)", () => {
    const syms = [makeSymbol({ id: 1, page_number: null }), makeSymbol({ id: 2, page_number: 1 })]
    // Page 1: the null-paged symbol stays (it's the only one without
    // a page) AND the page-1 symbol.
    const out = filterSymbolsByPage(syms, 1).map((s) => s.id)
    expect(out).toContain(1)
    expect(out).toContain(2)
  })

  it("returns everything when page < 1 (disabled filter)", () => {
    const syms = [makeSymbol({ id: 1, page_number: 1 }), makeSymbol({ id: 2, page_number: 2 })]
    expect(filterSymbolsByPage(syms, 0).map((s) => s.id)).toEqual([1, 2])
    expect(filterSymbolsByPage(syms, -1).map((s) => s.id)).toEqual([1, 2])
  })

  it("returns empty when nothing matches", () => {
    const syms = [makeSymbol({ id: 1, page_number: 5 })]
    expect(filterSymbolsByPage(syms, 2)).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// colorForSymbolClass
// ---------------------------------------------------------------------------

describe("colorForSymbolClass", () => {
  it("returns a valid HSL string", () => {
    const color = colorForSymbolClass("door")
    expect(color).toMatch(/^hsl\(\d+, 70%, 55%\)$/)
  })

  it("is deterministic — same class always returns the same colour", () => {
    expect(colorForSymbolClass("window")).toBe(colorForSymbolClass("window"))
  })

  it("returns different colours for different classes (most of the time)", () => {
    // We can't guarantee two arbitrary classes hash to different hues
    // (the wheel has 360 slots and our hash is 32-bit). We assert
    // a small sample of common classes produces varied colours so
    // the swatches in the legend are not all the same hue.
    const palette = new Set([
      colorForSymbolClass("door"),
      colorForSymbolClass("window"),
      colorForSymbolClass("toilet"),
      colorForSymbolClass("sink"),
      colorForSymbolClass("bed"),
      colorForSymbolClass("chair"),
    ])
    expect(palette.size).toBeGreaterThan(1)
  })

  it("handles empty / weird inputs without crashing", () => {
    expect(colorForSymbolClass("")).toMatch(/^hsl\(/)
    expect(colorForSymbolClass("_")).toMatch(/^hsl\(/)
    expect(colorForSymbolClass("a".repeat(1000))).toMatch(/^hsl\(/)
  })
})

// ---------------------------------------------------------------------------
// humaniseSymbolClass
// ---------------------------------------------------------------------------

describe("humaniseSymbolClass", () => {
  it.each([
    ["door", "Door"],
    ["single_door", "Single Door"],
    ["sliding door", "Sliding door"],
    ["bath_tub", "Bath Tub"],
    ["a", "A"],
    ["", ""],
  ])("humanises %j as %j", (input, expected) => {
    expect(humaniseSymbolClass(input)).toBe(expected)
  })

  it("collapses multiple underscores into single spaces", () => {
    expect(humaniseSymbolClass("foo___bar")).toBe("Foo Bar")
  })
})
