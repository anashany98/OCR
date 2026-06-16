/**
 * F7: the navigation config and the route handles must agree on
 * the title for every admin sub-route. This test asserts that
 * :data:`NAV_ROUTE_TITLES` covers every admin sub-path so a
 * developer who adds a new admin tab without a title still gets a
 * sensible label from the centralized config.
 */
import { describe, expect, it } from "vitest"

import { NAV_ROUTE_TITLES, titleForPath } from "./navigation"

describe("navigation config (F7)", () => {
  it("registers a title for every admin sub-route", () => {
    const expected = [
      "/admin/operativa",
      "/admin/sistema",
      "/admin/integraciones",
      "/admin/acceso",
      "/admin/calidad",
      "/admin/aprendizaje",
    ]
    for (const path of expected) {
      expect(NAV_ROUTE_TITLES[path], `missing title for ${path}`).toBeTruthy()
    }
  })

  it("registers a title for /documents/:id/annotate-plan (the path that used to fall through to Docu-Intel)", () => {
    // F7 explicitly addressed this path: the AGENTS.md said
    // ``getPageTitle`` did not cover it, leaving the breadcrumb
    // showing "Docu-Intel". Make sure the centralised map fills
    // the gap.
    expect(NAV_ROUTE_TITLES["/documents/:id/annotate-plan"]).toBe("Anotar plano")
  })

  it("titleForPath returns the canonical title for an exact match", () => {
    expect(titleForPath("/")).toBe("Dashboard")
    expect(titleForPath("/invoices")).toBe("Facturas")
    expect(titleForPath("/admin/calidad")).toBe("Administración · Calidad")
  })

  it("titleForPath falls back to the registered pattern for a parameterised path", () => {
    // /documents/123 -> matches /documents/:id
    expect(titleForPath("/documents/123")).toBe("Detalle de documento")
    // /documents/123/annotate-plan -> matches /documents/:id/annotate-plan
    expect(titleForPath("/documents/123/annotate-plan")).toBe("Anotar plano")
  })

  it("titleForPath returns the app name for an unknown path", () => {
    expect(titleForPath("/this/route/does/not/exist")).toBe("Docu-Intel")
  })
})
