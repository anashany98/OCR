import { act, renderHook } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"

import { useTableState } from "./useTableState"

describe("useTableState", () => {
  beforeEach(() => localStorage.clear())

  it("persists filters and resets pagination when filters change", () => {
    const { result } = renderHook(() => useTableState("documents", {
      pagination: { pageIndex: 3, pageSize: 25 },
    }))

    act(() => result.current.setFilter("status", "processed"))

    expect(result.current.filters).toEqual({ status: "processed" })
    expect(result.current.pagination).toEqual({ pageIndex: 0, pageSize: 25 })
    expect(localStorage.getItem("docu-intel:table:documents")).toContain("processed")

    act(() => result.current.reset())
    expect(result.current.filters).toBeUndefined()
    expect(localStorage.getItem("docu-intel:table:documents")).toBeNull()
  })
})
