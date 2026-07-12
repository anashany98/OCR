import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react"

type Density = "comfortable" | "compact"

interface DensityContextValue {
  density: Density
  setDensity: (d: Density) => void
  toggleDensity: () => void
}

const DensityContext = createContext<DensityContextValue>({
  density: "comfortable",
  setDensity: () => {},
  toggleDensity: () => {},
})

const STORAGE_KEY = "docu-intel:density"

function getInitialDensity(): Density {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === "compact" || saved === "comfortable") return saved
  } catch {
    // Storage can be unavailable in private browsing contexts.
  }
  return "comfortable"
}

export function DensityProvider({ children }: { children: ReactNode }) {
  const [density, setDensityState] = useState<Density>(getInitialDensity)

  const setDensity = (d: Density) => {
    setDensityState(d)
    try { localStorage.setItem(STORAGE_KEY, d) } catch {
      // Persistence is best-effort.
    }
  }

  const toggleDensity = useCallback(() => {
    setDensity(density === "comfortable" ? "compact" : "comfortable")
  }, [density])

  const value = useMemo(() => ({ density, setDensity, toggleDensity }), [density, toggleDensity])

  return <DensityContext.Provider value={value}>{children}</DensityContext.Provider>
}

export function useDensity() {
  return useContext(DensityContext)
}

/**
 * Returns compact-aware spacing classes.
 * Use `isCompact ? "py-1" : "py-2"` pattern in components.
 */
export function useDensityClasses() {
  const { density } = useDensity()
  const isCompact = density === "compact"
  return {
    isCompact,
    row: isCompact ? "py-1" : "py-2",
    cell: isCompact ? "px-2 py-1" : "px-3 py-2",
    section: isCompact ? "space-y-2" : "space-y-4",
    card: isCompact ? "p-3" : "p-5",
  }
}
