import { act, renderHook } from "@testing-library/react"
import { beforeEach, describe, expect, it } from "vitest"

import { DensityProvider, useDensity } from "./useDensity"

describe("useDensity", () => {
  beforeEach(() => localStorage.clear())

  it("restores and persists density preferences", () => {
    localStorage.setItem("docu-intel:density", "compact")
    const { result } = renderHook(() => useDensity(), { wrapper: DensityProvider })

    expect(result.current.density).toBe("compact")
    act(() => result.current.toggleDensity())

    expect(result.current.density).toBe("comfortable")
    expect(localStorage.getItem("docu-intel:density")).toBe("comfortable")
  })
})
