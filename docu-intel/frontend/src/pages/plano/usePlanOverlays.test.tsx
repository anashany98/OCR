import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { describe, expect, it, vi } from "vitest"

import { usePlanOverlays } from "./usePlanOverlays"

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe("usePlanOverlays", () => {
  it("loads base overlays and lazily enables optional overlay sources", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      const body = url.endsWith("/overlays")
        ? [{ region_type: "cajetin", bbox: [1, 2, 3, 4], label: "A-01", confidence: 0.9, page_number: 1 }]
        : url.endsWith("/chat-facts")
          ? [{ fact_type: "room", subject: "Sala", value: "101", bbox: null, page_number: 1, source_document: "a.pdf", confidence: 0.8 }]
          : []
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
    })
    vi.stubGlobal("fetch", fetchMock)

    const { result } = renderHook(() => usePlanOverlays(7, 11), { wrapper })

    await waitFor(() => expect(result.current.overlays).toHaveLength(1))
    expect(result.current.visibility.chatFacts).toBe(false)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    act(() => result.current.toggleOverlay("chatFacts"))
    await waitFor(() => expect(result.current.chatFacts).toHaveLength(1))
    expect(result.current.visibility.chatFacts).toBe(true)
  })

  it("does not request plan resources without a plan id", () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)

    const { result } = renderHook(() => usePlanOverlays(null, null), { wrapper })

    expect(result.current.overlays).toEqual([])
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
