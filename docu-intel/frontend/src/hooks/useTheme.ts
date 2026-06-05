import { useEffect, useState } from "react"

type Theme = "light" | "dark"

const STORAGE_KEY = "docu-intel:theme"

/**
 * Read the effective theme from localStorage or system preference.
 * Runs synchronously so we can apply the class before first paint to avoid
 * a light/dark flash (FOUC).
 */
function readInitialTheme(): Theme {
  if (typeof window === "undefined") return "light"
  const stored = window.localStorage.getItem(STORAGE_KEY) as Theme | null
  if (stored === "light" || stored === "dark") return stored
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === "dark") root.classList.add("dark")
  else root.classList.remove("dark")
}

// Apply once at module load (runs in main.tsx before React mounts).
const initial = readInitialTheme()
if (typeof document !== "undefined") {
  applyTheme(initial)
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(initial)

  useEffect(() => {
    // Re-sync if the system preference changes and user hasn't picked one.
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === "light" || stored === "dark") return
    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const onChange = (event: MediaQueryListEvent) => {
      const next: Theme = event.matches ? "dark" : "light"
      setThemeState(next)
      applyTheme(next)
    }
    mq.addEventListener("change", onChange)
    return () => mq.removeEventListener("change", onChange)
  }, [])

  function setTheme(next: Theme) {
    setThemeState(next)
    applyTheme(next)
    window.localStorage.setItem(STORAGE_KEY, next)
  }

  function toggle() {
    setTheme(theme === "dark" ? "light" : "dark")
  }

  return { theme, setTheme, toggle }
}
