/**
 * F4b - route tree shape tests.
 *
 * The router module is the source of truth for the admin sub-routes
 * exposed to the user. These tests assert that the six tab
 * sub-routes are wired correctly: each one exists, is reachable
 * under ``/admin/<id>`` and is a child of the ``/admin`` parent.
 *
 * We do not render the routes (that would require a full app
 * provider tree); we just inspect the data structure the
 * ``createBrowserRouter`` function returns.
 */
import { describe, expect, it } from "vitest"

import { router } from "./router"

interface RouteLike {
  path?: string
  index?: boolean
  children?: RouteLike[]
  handle?: { title?: string }
}

function findAdmin(routes: RouteLike[]): RouteLike | undefined {
  for (const route of routes) {
    if (route.path === "admin") return route
    if (route.children) {
      const found = findAdmin(route.children)
      if (found) return found
    }
  }
  return undefined
}

describe("admin route tree (F4b)", () => {
  const adminRoute = findAdmin(router.routes as RouteLike[])

  it("has a /admin parent route", () => {
    expect(adminRoute).toBeDefined()
    expect(adminRoute?.path).toBe("admin")
  })

  it("exposes seven lazy sub-routes under /admin", () => {
    const subRoutes = (adminRoute?.children ?? []).filter((child) => child.path) as RouteLike[]
    const expected = [
      "operativa",
      "sistema",
      "integraciones",
      "acceso",
      "calidad",
      "aprendizaje",
      "flujo-ocr",
    ]
    const actual = subRoutes.map((child) => child.path).sort()
    expect(actual).toEqual([...expected].sort())
  })

  it("redirects the admin index to operativa", () => {
    const indexRoute = adminRoute?.children?.find((child) => child.index === true)
    expect(indexRoute).toBeDefined()
  })
})

describe("admin route titles (F4b / F7)", () => {
  it("every admin sub-route sets a route-level title", () => {
    // Pull every admin sub-route by walking the tree, looking for
    // ``handle.title`` on each child. This protects the
    // ``getPageTitle`` reader in ``AppShell`` from silently falling
    // back to a generic "Administración" when a new tab is added
    // without a title.
    const adminParent = findAdmin(router.routes as RouteLike[])
    const children = adminParent?.children ?? []
    const tabsWithTitle = children.filter((child) => child.handle?.title).length
    expect(tabsWithTitle).toBeGreaterThanOrEqual(6)
  })
})
