import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { useContext } from "react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it } from "vitest"

import { AdminPage } from "./AdminPage"
import { AdminReprocessContext } from "./admin/useAdminReprocess"

/**
 * F4b refactor: the admin shell no longer pushes 30+ queries into a
 * single ``useOutletContext`` payload. Instead each tab mounts its
 * own domain hook and the only shared state — the bulk-reprocess
 * filter form and the confirm dialog flag — is published through
 * ``AdminReprocessContext``. The test below verifies that
 * ``AdminPage`` wraps the outlet in that provider with the
 * default no-op values.
 */
function AdminChildRoute() {
  const ctx = useContext(AdminReprocessContext)
  return (
    <div data-testid="admin-context">
      {ctx ? `status=${ctx.status || "default"}` : "no-context"}
    </div>
  )
}

describe("AdminPage", () => {
  it("provides AdminReprocessContext to nested admin routes", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/admin/operativa"]}>
          <Routes>
            <Route path="/admin" element={<AdminPage />}>
              <Route path="operativa" element={<AdminChildRoute />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(screen.getByTestId("admin-context")).toHaveTextContent("status=default")
  })
})
