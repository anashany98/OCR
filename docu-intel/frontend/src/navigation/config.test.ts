/**
 * Navigation config contract tests.
 *
 * Two invariants this test enforces:
 *   1. Every admin sub-route declared by the router has a
 *      canonical title in :data:`NAV_ROUTE_TITLES` so the
 *      :func:`titleForPath` reader in ``AppShell`` never falls
 *      back to a generic label.
 *   2. :func:`titleForPath` resolves exact paths, parameterised
 *      paths (``/documents/123`` -> ``/documents/:id``) and
 *      unknown paths to the expected values.
 */
import { describe, expect, it } from "vitest"

import { NAV_ROUTE_TITLES, titleForPath } from "./config"

describe("navigation config", () => {
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
    // The original AppShell.getPageTitle did not cover this path,
    // leaving the breadcrumb showing "Docu-Intel". The centralised
    // map fills the gap.
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
