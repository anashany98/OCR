import { describe, expect, it } from "vitest"

import {
  buildActiveFilters,
  clientFilter,
  getMatchReason,
  modeLabel,
  toSearchMode,
} from "./useSearchPage"
import type { SearchResult } from "@/types/api"

const baseResult: SearchResult = {
  document_id: 1,
  original_filename: "factura.pdf",
  document_type: "factura",
  status: "processed",
  page_number: 1,
  block_id: null,
  ocr_confidence: 0.92,
  excerpt: "Total 1.245,60 €",
  score: 0.85,
  source_type: "hybrid",
}

describe("buildActiveFilters", () => {
  it("returns an empty list when no filter is set", () => {
    expect(
      buildActiveFilters({
        type: "",
        status: "",
        supplier: "",
        client: "",
        minConfidencePercent: "",
        sourcePath: "",
        dateFrom: "",
        dateTo: "",
      }),
    ).toEqual([])
  })

  it("emits a chip for every populated field", () => {
    const chips = buildActiveFilters({
      type: "factura",
      status: "needs_review",
      supplier: "ACME",
      client: "",
      minConfidencePercent: "80",
      sourcePath: "presupuestos/2026",
      dateFrom: "2026-01-01",
      dateTo: "2026-12-31",
    })
    expect(chips).toContain("tipo: factura")
    expect(chips).toContain("estado: needs_review")
    expect(chips).toContain("proveedor: ACME")
    expect(chips).not.toContain("cliente: ")
    expect(chips).toContain("confianza ≥80%")
    expect(chips).toContain("carpeta: presupuestos/2026")
    expect(chips).toContain("desde: 2026-01-01")
    expect(chips).toContain("hasta: 2026-12-31")
  })
})

describe("clientFilter", () => {
  const items: SearchResult[] = [
    baseResult,
    { ...baseResult, document_id: 2, document_type: "presupuesto" },
    { ...baseResult, document_id: 3, status: "needs_review" },
    { ...baseResult, document_id: 4, ocr_confidence: 0.5 },
  ]

  it("returns the input unchanged when no filter is set", () => {
    expect(clientFilter(items, {})).toBe(items)
  })

  it("filters by document type", () => {
    const out = clientFilter(items, { type: "factura" })
    expect(out.map((r) => r.document_id)).toEqual([1, 3, 4])
  })

  it("filters by status", () => {
    const out = clientFilter(items, { status: "needs_review" })
    expect(out.map((r) => r.document_id)).toEqual([3])
  })

  it("filters by minimum OCR confidence (as percent)", () => {
    const out = clientFilter(items, { minConfidencePercent: "80" })
    expect(out.map((r) => r.document_id)).toEqual([1, 2, 3])
  })

  it("combines filters with AND semantics", () => {
    const out = clientFilter(items, { type: "factura", status: "needs_review" })
    expect(out.map((r) => r.document_id)).toEqual([3])
  })
})

describe("getMatchReason", () => {
  it("describes a hybrid match with low OCR", () => {
    const text = getMatchReason({ ...baseResult, source_type: "hybrid", ocr_confidence: 0.5 })
    expect(text).toContain("combinada")
    expect(text).toContain("baja confianza")
  })

  it("returns empty string for healthy exact match", () => {
    const text = getMatchReason({ ...baseResult, source_type: "text", ocr_confidence: 0.9 })
    expect(text).toContain("textual exacta")
    expect(text).not.toContain("baja confianza")
  })
})

describe("modeLabel", () => {
  it("maps each source_type to a human label", () => {
    expect(modeLabel("text")).toBe("Textual")
    expect(modeLabel("semantic")).toBe("Semántico")
    expect(modeLabel("hybrid")).toBe("Híbrido")
    expect(modeLabel("guided")).toBe("Exacto")
    expect(modeLabel("anything-else")).toBe("Score")
  })
})

describe("toSearchMode", () => {
  it("accepts known modes", () => {
    expect(toSearchMode("hybrid")).toBe("hybrid")
    expect(toSearchMode("guided:budget")).toBe("guided:budget")
  })

  it("falls back to hybrid for unknown values", () => {
    expect(toSearchMode("garbage")).toBe("hybrid")
  })
})
