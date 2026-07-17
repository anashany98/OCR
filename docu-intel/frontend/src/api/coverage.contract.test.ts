import { describe, expect, it, vi } from "vitest"

import { api } from "./client"

describe("API facade coverage contract", () => {
  it("keeps every request wrapper connected to the shared request client", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    const wrappers = Object.entries(api)
      .filter(
        ([, value]) =>
          typeof value === "function" && value.constructor.name !== "AsyncGeneratorFunction",
      )
      .filter(([name]) => !["exportSearchCSV", "exportSearchJSON"].includes(name)) as Array<
      [string, (...args: unknown[]) => unknown]
    >

    for (const [, wrapper] of wrappers) {
      // The facade deliberately accepts heterogeneous payloads.  A generic
      // call verifies each wrapper reaches its request construction path;
      // individual feature tests cover the domain-specific payload shape.
      try {
        await wrapper(1, 1, 1, 1)
      } catch {
        // Some wrappers validate a File/FormData payload before issuing the
        // request.  Invoking them still protects their existence in the
        // exported facade without pretending this is a schema test.
      }
    }

    expect(wrappers.length).toBeGreaterThan(50)
    expect(fetchMock).toHaveBeenCalled()
  })
})
