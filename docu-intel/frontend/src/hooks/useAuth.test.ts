import { describe, expect, it, vi } from "vitest"

import { redirectToLoginOnUnauthorized } from "./useAuth"

describe("redirectToLoginOnUnauthorized", () => {
  it("does not reload the login page after its expected unauthenticated /me response", () => {
    const replace = vi.fn()

    redirectToLoginOnUnauthorized({ pathname: "/login", replace })

    expect(replace).not.toHaveBeenCalled()
  })

  it("redirects unauthenticated protected routes once", () => {
    const replace = vi.fn()

    redirectToLoginOnUnauthorized({ pathname: "/documents", replace })

    expect(replace).toHaveBeenCalledOnce()
    expect(replace).toHaveBeenCalledWith("/login")
  })
})
