import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react"

import { api, ApiError, setUnauthorizedHandler } from "@/api/client"
import type { User } from "@/types/api"

type AuthContextValue = {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

/**
 * A 401 is expected while the login form is open.  Redirecting with
 * ``window.location.href`` from that same route reloads the complete SPA;
 * the new provider calls ``/auth/me`` again, receives another 401 and loops
 * indefinitely.  Only navigate when the user is currently elsewhere.
 */
export function redirectToLoginOnUnauthorized(location: Pick<Location, "pathname" | "replace"> = window.location) {
  if (location.pathname !== "/login") location.replace("/login")
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  // F8-01: global 401 handler — redirect to login on any unauthorized response
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null)
      redirectToLoginOnUnauthorized()
    })
  }, [])

  useEffect(() => {
    let active = true
    api
      .me()
      .then((currentUser) => {
        if (active) setUser(currentUser)
      })
      .catch((error) => {
        if (error instanceof ApiError && error.status !== 401) console.error(error)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      login: async (email, password) => {
        const response = await api.login(email, password)
        setUser(response.user)
      },
      logout: async () => {
        try {
          await api.logout()
        } catch {
          // Ignore network errors — clear local state regardless
        }
        setUser(null)
      },
    }),
    [loading, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error("useAuth must be used inside AuthProvider")
  return context
}
