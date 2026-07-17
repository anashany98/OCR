import { afterEach, describe, expect, it, vi } from "vitest"

import { exportCsv } from "./exportCsv"

describe("exportCsv", () => {
  afterEach(() => vi.restoreAllMocks())

  it("creates an UTF-8 download and escapes formatted values", async () => {
    const createObjectURL = vi.fn(() => "blob:csv")
    const revokeObjectURL = vi.fn()
    vi.stubGlobal("URL", { createObjectURL, revokeObjectURL })
    const click = vi.fn()
    const appendChild = vi.spyOn(document.body, "appendChild")
    const removeChild = vi.spyOn(document.body, "removeChild")
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) => {
      const node = document.createElementNS(
        "http://www.w3.org/1999/xhtml",
        tag,
      ) as HTMLAnchorElement
      node.click = click
      return node
    }) as typeof document.createElement)

    exportCsv(
      [
        { header: "Nombre", accessor: "name" as const },
        { header: "Importe", accessor: "amount" as const, format: (value) => `${value} EUR` },
      ],
      [{ name: 'A, "B"', amount: 12 }],
      "informe",
    )

    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(click).toHaveBeenCalledOnce()
    expect(appendChild).toHaveBeenCalledOnce()
    expect(removeChild).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:csv")
  })
})
