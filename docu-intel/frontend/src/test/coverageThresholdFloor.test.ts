// S5.2 — Vitest coverage threshold floor.
//
// The MiniMax M3 (FASE 5.2) plan asks to lower the test
// coverage gate from the previous 10 % global floor to a
// realistic per-folder budget. The current configuration
// (``vite.config.ts``) sets lines/functions/statements to
// 30 % and branches to 20 %. ``npm run test`` is green.
//
// This test pins the floor so a future refactor that drops the
// threshold to "0" (effectively disabling the gate) is caught.
// We assert *minimum* values — a higher threshold is always
// allowed and is encouraged.
import { describe, expect, it } from "vitest"

import viteConfig from "/vite.config"

type Thresholds = {
  lines: number
  functions: number
  branches: number
  statements: number
}

function extractThresholds(config: unknown): Thresholds {
  // The vite config export is a function that takes an
  // ``{ command, mode }`` arg and returns the full config
  // object. We invoke it with a fake env so the test does not
  // need a real CLI flag parser.
  const result =
    typeof config === "function"
      ? (config as (env: Record<string, unknown>) => unknown)({
          command: "test",
          mode: "test",
        })
      : config
  const test = (result as { test?: { coverage?: { thresholds?: Thresholds } } })
    .test
  const thresholds = test?.coverage?.thresholds
  if (!thresholds) {
    throw new Error(
      "vite.config.ts does not declare test.coverage.thresholds",
    )
  }
  for (const key of ["lines", "functions", "branches", "statements"] as const) {
    if (typeof thresholds[key] !== "number") {
      throw new Error(`threshold "${key}" is missing or not a number`)
    }
  }
  return thresholds as Thresholds
}

describe("vitest coverage threshold", () => {
  const thresholds = extractThresholds(viteConfig)

  it("lines floor is realistic (>= 25 %)", () => {
    // The plan agreed on 30 % for lines. We pin a lower bound of
    // 25 % so a drop to 0 is caught without breaking the build
    // for legitimate 28–29 % transitions that happen during a
    // refactor.
    expect(thresholds.lines).toBeGreaterThanOrEqual(25)
  })

  it("functions floor matches lines floor", () => {
    expect(thresholds.functions).toBe(thresholds.lines)
  })

  it("statements floor matches lines floor", () => {
    expect(thresholds.statements).toBe(thresholds.lines)
  })

  it("branches floor is realistic (>= 20 %)", () => {
    expect(thresholds.branches).toBeGreaterThanOrEqual(20)
  })
})
