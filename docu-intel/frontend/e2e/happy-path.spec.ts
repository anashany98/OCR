/**
 * S3.3 (Sprint 3) — end-to-end happy path.
 *
 * The test covers the main user flow on the deployed app:
 *
 *   1. Login as the admin user.
 *   2. Land on the dashboard.
 *   3. Open the Search page, run a hybrid search.
 *   4. Click a result to view the document detail.
 *   5. Open the Chat page, send a question, see a streamed
 *      response.
 *   6. Logout.
 *
 * The test uses ``page.route`` to mock the document search and
 * chat endpoints so it does not need a fully populated backend
 * to pass. This keeps the e2e suite fast (a few seconds) and
 * deterministic. The mock payloads are realistic enough that
 * a UI regression (missing "search results" card, broken
 * streaming bubble) still fails the test.
 *
 * The login + dashboard navigation steps are real (no mock) so
 * a routing or auth-redirect regression is caught too. They
 * require the running backend to accept the seeded admin
 * credentials (``admin@example.local`` / admin password from
 * the env).
 */
import { expect, test } from "@playwright/test"

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@example.local"
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "test_admin_password_16"

/**
 * Mock the slow / stateful backend endpoints. The login +
 * dashboard + auth-me endpoints are real (we want a routing
 * regression caught); the search + chat endpoints are mocked
 * (we want UI regressions caught without depending on the
 * heavy inference stack).
 */
async function mockHeavyEndpoints(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/search/hybrid", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          document_id: 42,
          original_filename: "presupuesto-245745.pdf",
          document_type: "presupuesto",
          status: "processed",
          page_number: 1,
          block_id: null,
          score: 0.94,
          excerpt: "Presupuesto cliente A — total 12.450 EUR",
          ocr_confidence: 0.91,
          source_type: "hybrid_rrf",
          source_path: "presupuestos/245745",
        },
        {
          document_id: 43,
          original_filename: "factura-245801.pdf",
          document_type: "factura",
          status: "processed",
          page_number: 2,
          block_id: null,
          score: 0.78,
          excerpt: "Factura cliente B — base 8.200 EUR",
          ocr_confidence: 0.85,
          source_type: "semantic_chunk",
          source_path: "facturas/245801",
        },
      ]),
    })
  })

  await page.route("**/api/v1/ai/ask/stream", async (route) => {
    // Minimal SSE response with one delta + a final end event.
    const body = [
      'event: start\ndata: {"model":"qwen2.5-32b-instruct"}\n\n',
      'event: delta\ndata: {"text":"Sí, el cliente A tiene un presupuesto de 12.450 EUR."}\n\n',
      'event: end\ndata: {"answer":"Sí, el cliente A tiene un presupuesto de 12.450 EUR.","model":"qwen2.5-32b-instruct","confidence":0.86,"sources":[],"followups":[],"fallback":false}\n\n',
    ].join("")
    await route.fulfill({
      status: 200,
      headers: { "content-type": "text/event-stream" },
      body,
    })
  })
}

test.describe("happy path", () => {
  test("login → search → view document → chat → logout", async ({ page }) => {
    await mockHeavyEndpoints(page)

    // ---- 1. Login --------------------------------------------------------
    await page.goto("/login")
    await page.getByLabel(/email|correo/i).fill(ADMIN_EMAIL)
    await page.getByLabel(/password|contrase/i).fill(ADMIN_PASSWORD)
    await page.getByRole("button", { name: /entrar|iniciar|login|sign in/i }).click()
    // After login the SPA routes to "/" (the dashboard).
    await page.waitForURL(/\/(?!login)/, { timeout: 15_000 })

    // ---- 2. Dashboard ----------------------------------------------------
    // The dashboard renders inside AppShell; a content landmark
    // makes the assertion stable across layout refactors.
    await expect(page.getByRole("main")).toBeVisible({ timeout: 5_000 })

    // ---- 3. Search -------------------------------------------------------
    await page.goto("/search")
    await page.getByPlaceholder(/buscar|search/i).fill("presupuesto cliente A")
    // The search is a manual submit; find the form's submit button
    // by walking up from the input.
    await page.getByRole("button", { name: /buscar|search/i }).first().click()
    // The mock returns two results; the first card is the presupuesto.
    await expect(page.getByText("presupuesto-245745.pdf")).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText("12.450 EUR")).toBeVisible()

    // ---- 4. Open document detail ---------------------------------------
    await page.getByText("presupuesto-245745.pdf").click()
    // The detail page URL is /documents/<id>. The mock returned
    // document_id=42 so we expect /documents/42.
    await page.waitForURL(/\/documents\/\d+/, { timeout: 10_000 })
    await expect(page.getByText(/presupuesto-245745\.pdf|presupuesto cliente A/i)).toBeVisible()

    // ---- 5. Chat ---------------------------------------------------------
    await page.goto("/chat")
    const chatInput = page.getByPlaceholder(/preguntar|ask|chat|message/i).first()
    await chatInput.fill("¿Cuánto tiene el cliente A?")
    await chatInput.press("Enter")
    // The mocked stream emits a delta with the answer text. The
    // bubble appears once the SSE delta is parsed.
    await expect(page.getByText(/12\.450 EUR/)).toBeVisible({ timeout: 15_000 })

    // ---- 6. Logout ------------------------------------------------------
    // The exact logout UX is in the AppShell user menu; we click the
    // avatar / user-name trigger and the logout button. If the
    // structure changes this assertion is the first to break; that
    // is by design.
    const userMenu = page.getByRole("button", { name: /admin|perfil|user/i }).first()
    if (await userMenu.isVisible().catch(() => false)) {
      await userMenu.click()
      const logout = page.getByRole("button", { name: /logout|salir|cerrar sesión/i }).first()
      if (await logout.isVisible().catch(() => false)) {
        await logout.click()
      }
    }
    // The SPA clears the session and routes back to /login
    // (handled by the RequireAuth route guard).
    await page.waitForURL(/login/, { timeout: 5_000 })
  })
})
