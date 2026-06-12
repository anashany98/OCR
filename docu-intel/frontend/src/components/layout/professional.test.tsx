import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import { EmptyState } from "@/components/layout/EmptyState"
import { MetricTile } from "@/components/layout/MetricTile"

describe("professional layout primitives", () => {
  it("renders metric tiles with labels, values and trend context", () => {
    const html = renderToStaticMarkup(
      <MetricTile title="OCR pendiente" value={9} meta="3 críticos" tone="warning" />,
    )

    expect(html).toContain("OCR pendiente")
    expect(html).toContain("9")
    expect(html).toContain("3 críticos")
  })

  it("renders empty states with a direct recovery action", () => {
    const html = renderToStaticMarkup(
      <EmptyState
        title="Sin documentos"
        description="Sube o escanea carpetas."
        action="Escanear"
      />,
    )

    expect(html).toContain("Sin documentos")
    expect(html).toContain("Sube o escanea carpetas.")
    expect(html).toContain("Escanear")
  })
})
