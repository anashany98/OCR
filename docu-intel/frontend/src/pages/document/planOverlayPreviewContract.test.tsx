// S5.1 — Plan overlay preview embedded in DocumentDetailPage.
//
// Contract test: the component renders the overlay counts it receives
// from ``usePlanOverlays`` instead of always falling back to the empty
// state. This pins the bug where ``DocumentDetailPage`` rendered
// ``<PlanOverlayPreview planId={null} />``, which made the hook skip
// every fetch (``enabled: !!planId``) so the preview was permanently
// empty.
//
// To exercise the real render path we mount the component with a
// QueryClientProvider + MemoryRouter and stub ``fetch`` to feed a known
// overlay set. We pass ``planId`` explicitly so the test is robust to
// the plan-resolution hook and focuses on the render contract.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { PlanOverlayPreview } from "./PlanOverlayPreview"

function wrapper(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

function stubPlansFetch(overlays: unknown[], planId = 42) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    // usePlanForDocument lists plans; return one matching the plan id
    // so the auto-resolution path also works when no planId is passed.
    const body = url.includes("/overlays")
      ? overlays
      : url.includes(`/plans?limit=`)
        ? [{ id: planId, document_id: 1 }]
        : []
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
  })
}

describe("PlanOverlayPreview", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it("renders overlay counts when overlays exist", async () => {
    const fetchMock = stubPlansFetch([
      {
        region_type: "cajetin_title",
        bbox: [1, 2, 3, 4],
        label: "A-01",
        confidence: 0.9,
        page_number: 1,
      },
      {
        region_type: "legend_block",
        bbox: [5, 6, 7, 8],
        label: "L1",
        confidence: 0.8,
        page_number: 1,
      },
    ])
    vi.stubGlobal("fetch", fetchMock)

    render(
      wrapper(
        <PlanOverlayPreview documentId={1} planId={42} />,
      ),
    )

    await waitFor(() => {
      expect(screen.getByTestId("plan-overlay-count-cajetin")).toHaveTextContent("1")
    })
    expect(screen.getByTestId("plan-overlay-count-legend")).toHaveTextContent("1")
    // The empty-state paragraph must NOT appear when there are overlays.
    expect(screen.queryByText(/aun no tiene anotaciones/i)).toBeNull()
  })

  it("shows the empty state when there are no overlays", async () => {
    const fetchMock = stubPlansFetch([])
    vi.stubGlobal("fetch", fetchMock)

    render(wrapper(<PlanOverlayPreview documentId={1} planId={42} />))

    await waitFor(() => {
      expect(screen.getByText(/aun no tiene anotaciones/i)).toBeInTheDocument()
    })
    expect(screen.queryByTestId("plan-overlay-count-cajetin")).toBeNull()
  })

  it("resolves the plan id from the document id when planId is omitted", async () => {
    // Regression guard for the original bug: DocumentDetailPage passed
    // ``planId={null}``, which left the hook disabled forever. With the
    // prop omitted, the component must resolve the plan itself and
    // fetch overlays.
    const fetchMock = stubPlansFetch(
      [
        {
          region_type: "cajetin_main",
          bbox: [0, 0, 1, 1],
          label: "C1",
          confidence: 0.5,
          page_number: 1,
        },
      ],
      42,
    )
    vi.stubGlobal("fetch", fetchMock)

    render(wrapper(<PlanOverlayPreview documentId={1} />))

    await waitFor(() => {
      expect(screen.getByTestId("plan-overlay-count-cajetin")).toHaveTextContent("1")
    })
  })
})
