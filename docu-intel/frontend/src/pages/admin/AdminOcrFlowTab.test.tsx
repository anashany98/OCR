import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"

import { AdminOcrFlowTab } from "./AdminOcrFlowTab"

vi.mock("./useAdminOcrFlowData", () => ({
  useOcrFlowLive: () => ({
    data: {
      jobs: [
        {
          job_id: 1,
          document_id: 42,
          original_filename: "factura.pdf",
          job_type: "extract",
          status: "started",
          started_at: new Date().toISOString(),
          retries: 0,
          error: null,
        },
      ],
    },
  }),
  useOcrFlowDocument: () => ({
    data: {
      steps: [
        {
          kind: "page.processed",
          at: new Date().toISOString(),
          details: {
            page_number: 1,
            ocr_engine: "paddleocr",
            ocr_confidence: 0.9,
            cascade_attempts: [
              {
                id: 1,
                tier: "tesseract",
                tier_index: 1,
                success: true,
                duration_ms: 412,
                confidence: 0.3,
                reason: "no_improvement",
                error_message: null,
              },
              {
                id: 2,
                tier: "paddleocr",
                tier_index: 2,
                success: true,
                duration_ms: 891,
                confidence: 0.9,
                reason: "ok",
                error_message: null,
              },
            ],
          },
          error: null,
        },
      ],
    },
  }),
}))

describe("AdminOcrFlowTab", () => {
  it("shows the two tabs and renders the live job table", () => {
    const client = new QueryClient()
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AdminOcrFlowTab />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByRole("tab", { name: "En directo" })).toBeInTheDocument()
    expect(screen.getByRole("tab", { name: "Por documento" })).toBeInTheDocument()
    // The live tab is selected by default, so the job row is visible.
    expect(screen.getByText("factura.pdf")).toBeInTheDocument()
  })
})
