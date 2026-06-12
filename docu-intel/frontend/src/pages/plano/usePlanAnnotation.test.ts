import { describe, expect, it } from "vitest"

import { polygonAreaM2, SVG_W, SVG_H } from "./usePlanAnnotation"

describe("polygonAreaM2", () => {
  it("returns 0 for an empty polygon", () => {
    expect(polygonAreaM2([], 0.01)).toBe(0)
  })

  it("returns 0 for a polygon with fewer than 3 points", () => {
    expect(
      polygonAreaM2(
        [
          { x: 0, y: 0 },
          { x: 10, y: 0 },
        ],
        0.01,
      ),
    ).toBe(0)
  })

  it("computes the area of a 100x100 px square at 1:100 scale (1px=1m)", () => {
    // Square 100x100 px, 1px = 1m => area = 100*100 = 10_000 m^2
    const poly = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
      { x: 0, y: 100 },
    ]
    expect(polygonAreaM2(poly, 1.0)).toBeCloseTo(10_000, 2)
  })

  it("computes the area of a 100x100 px square at 1:1000 scale (1px=0.1m)", () => {
    // Same polygon, 10x smaller linear => 100x smaller area
    const poly = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
      { x: 0, y: 100 },
    ]
    expect(polygonAreaM2(poly, 0.1)).toBeCloseTo(100, 2)
  })

  it("is order-independent (shoelace is unsigned)", () => {
    const cw = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 100 },
      { x: 0, y: 100 },
    ]
    const ccw = [...cw].reverse()
    expect(polygonAreaM2(cw, 1.0)).toBeCloseTo(polygonAreaM2(ccw, 1.0), 6)
  })
})

describe("SVG dimensions", () => {
  it("exports the nominal coordinate system used by the canvas", () => {
    expect(SVG_W).toBe(1200)
    expect(SVG_H).toBe(850)
  })
})
