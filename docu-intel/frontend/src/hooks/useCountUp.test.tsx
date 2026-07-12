import { act, renderHook } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useCountUp } from "./useCountUp"

describe("useCountUp", () => {
  afterEach(() => vi.restoreAllMocks())

  it("keeps its initial target and animates a target change", () => {
    let frame: FrameRequestCallback | undefined
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      frame = callback
      return 1
    })
    vi.stubGlobal("cancelAnimationFrame", vi.fn())
    vi.spyOn(performance, "now").mockReturnValue(0)

    const { result, rerender } = renderHook(({ target }) => useCountUp(target, 100, 1), {
      initialProps: { target: 10 },
    })
    expect(result.current).toBe(10)

    rerender({ target: 20 })
    act(() => frame?.(100))
    expect(result.current).toBe(20)
  })
})
