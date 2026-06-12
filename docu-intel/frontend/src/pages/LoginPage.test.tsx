import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { LoginPage } from "@/pages/LoginPage"
import { AuthProvider } from "@/hooks/useAuth"
import { api } from "@/api/client"
import type { User } from "@/types/api"

const EMAIL_INPUT = (): HTMLInputElement =>
  screen.getByPlaceholderText("tecnico@empresa.com") as HTMLInputElement
const PASSWORD_INPUT = (): HTMLInputElement =>
  document.querySelector('input[type="password"]') as HTMLInputElement

const sampleUser: User = {
  id: 1,
  email: "admin@local",
  name: "Admin",
  role: "admin",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
}

function renderLogin() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe("LoginPage", () => {
  beforeEach(() => {
    // Default: /auth/me returns 401 (not logged in)
    vi.spyOn(api, "me").mockRejectedValue(Object.assign(new Error("401"), { status: 401 }))
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("renders the email and password inputs and the submit button", async () => {
    renderLogin()
    expect(await screen.findByPlaceholderText("tecnico@empresa.com")).toBeInTheDocument()
    expect(document.querySelector('input[type="password"]')).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /entrar/i })).toBeInTheDocument()
  })

  it("submits credentials and shows an error when login fails", async () => {
    vi.spyOn(api, "login").mockRejectedValue(new Error("Credenciales inválidas"))
    const user = userEvent.setup()
    renderLogin()

    await user.type(EMAIL_INPUT(), "admin@local")
    await user.type(PASSWORD_INPUT(), "wrong-password")
    await user.click(screen.getByRole("button", { name: /entrar/i }))

    expect(await screen.findByText(/credenciales inv[aá]lidas/i)).toBeInTheDocument()
  })

  it("disables the submit button while the request is in flight", async () => {
    let resolveLogin: (value: { access_token: string; user: User }) => void = () => {}
    const pendingLogin = new Promise<{ access_token: string; user: User }>((resolve) => {
      resolveLogin = resolve
    })
    vi.spyOn(api, "login").mockReturnValueOnce(
      pendingLogin as unknown as ReturnType<typeof api.login>,
    )

    const user = userEvent.setup()
    renderLogin()

    await user.type(EMAIL_INPUT(), "admin@local")
    await user.type(PASSWORD_INPUT(), "any-password")
    await user.click(screen.getByRole("button", { name: /entrar/i }))

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /entrar|entrando/i })).toBeDisabled()
    })

    // Clean up: resolve the promise so the test doesn't hang.
    resolveLogin({ access_token: "token", user: sampleUser })
  })
})
