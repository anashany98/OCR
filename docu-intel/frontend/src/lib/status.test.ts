import { describe, expect, it } from "vitest"

import { statusTone, severityTone } from "@/lib/status"

describe("statusTone", () => {
  it("maps operational document and job states to semantic tones", () => {
    expect(statusTone("processed")).toBe("success")
    expect(statusTone("processed_ok")).toBe("success")
    expect(statusTone("pending")).toBe("warning")
    expect(statusTone("processing")).toBe("info")
    expect(statusTone("needs_human_review")).toBe("warning")
    expect(statusTone("failed")).toBe("danger")
    expect(statusTone("duplicate")).toBe("neutral")
  })

  it("falls back to neutral for unknown states", () => {
    expect(statusTone("external_custom_state")).toBe("neutral")
  })
})

describe("severityTone", () => {
  it("normalizes alert severities to the same semantic tone scale", () => {
    expect(severityTone("critical")).toBe("danger")
    expect(severityTone("error")).toBe("danger")
    expect(severityTone("warning")).toBe("warning")
    expect(severityTone("info")).toBe("info")
    expect(severityTone("unknown")).toBe("neutral")
  })
})
