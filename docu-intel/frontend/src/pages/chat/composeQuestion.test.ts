import { describe, expect, it } from "vitest"

import { composeQuestion } from "./composeQuestion"

describe("composeQuestion", () => {
  it("returns the question verbatim when no filters are set", () => {
    expect(composeQuestion("¿Cuánto factura proveedor X?", { supplier: "", documentType: "" })).toBe(
      "¿Cuánto factura proveedor X?",
    )
  })

  it("ignores whitespace-only filter values", () => {
    const result = composeQuestion("hola", { supplier: "   ", documentType: "  " })
    expect(result).toBe("hola")
  })

  it("appends a single filter", () => {
    const result = composeQuestion("¿Total?", { supplier: "ACME", documentType: "" })
    expect(result).toContain("Filtros activos: proveedor: ACME")
    expect(result.startsWith("¿Total?")).toBe(true)
  })

  it("appends both filters in order", () => {
    const result = composeQuestion("¿Total?", { supplier: "ACME", documentType: "factura" })
    expect(result).toContain("proveedor: ACME")
    expect(result).toContain("tipo documental: factura")
    expect(result.indexOf("proveedor")).toBeLessThan(result.indexOf("tipo documental"))
  })

  it("trims the filter values", () => {
    const result = composeQuestion("q", { supplier: "  ACME  ", documentType: "factura " })
    expect(result).toContain("proveedor: ACME")
    expect(result).toContain("tipo documental: factura")
    expect(result).not.toContain("factura ")
  })
})
