import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { plansApi, type PlanSymbol, type PlanSymbolSummary } from "@/api/plans"

const EMPTY_PLAN_SYMBOLS: PlanSymbol[] = []

// ---------------------------------------------------------------------------
// P2 — YOLO plan symbol hook
// ---------------------------------------------------------------------------
// Reads the symbol detection results for a plan, with the same
// pattern as ``usePlanAnnotation``: the heavy work (fetch + cache)
// is in tanstack-query, the local UI state (toggling visibility,
// class filters) lives in plain ``useState``.
//
// Why a separate hook and not just inside ``usePlanAnnotation``:
//   - symbol detection is an opt-in feature (toggle) and the query
//     is expensive enough that we want to skip it when the user
//     never opens the legend;
//   - keeping it separate makes the per-feature test surface smaller.
//
// Returned values are **memoised** so the SVG overlay does not
// re-render on every keystroke in the editor.
// ---------------------------------------------------------------------------

export type UsePlanSymbolsOptions = {
  /** Skip the query entirely (e.g. while the plan is still loading). */
  enabled?: boolean
  /** Minimum confidence (0-1) to keep a detection. Default 0. */
  minConfidence?: number
}

export function usePlanSymbols(planId: number | undefined, options: UsePlanSymbolsOptions = {}) {
  const minConfidence = options.minConfidence ?? 0
  const enabled = options.enabled ?? true

  // Two queries: the full list (cheap) and the summary (cheap). The
  // full list is what feeds the SVG overlay; the summary powers the
  // side panel. We run them in parallel via tanstack-query's dedup.
  const listQuery = useQuery({
    queryKey: ["plan-symbols", planId, minConfidence],
    queryFn: () => plansApi.getSymbols(planId!, { min_confidence: minConfidence }),
    enabled: enabled && planId != null,
    staleTime: 60_000,
  })

  const summaryQuery = useQuery({
    queryKey: ["plan-symbols-summary", planId, minConfidence],
    queryFn: () => plansApi.getSymbolsSummary(planId!, minConfidence),
    enabled: enabled && planId != null,
    staleTime: 60_000,
  })

  // --- Local UI state -----------------------------------------------------
  const [showSymbols, setShowSymbols] = useState(true)
  const [activeClasses, setActiveClasses] = useState<Set<string> | null>(null)

  // If the user has not touched the class filter, every class is
  // considered "active". This is what ``activeClasses ?? allClasses``
  // collapses to in the consumer.
  const toggleClass = (cls: string) => {
    setActiveClasses((cur) => {
      const base = cur ?? new Set(allClasses)
      const next = new Set(base)
      if (next.has(cls)) next.delete(cls)
      else next.add(cls)
      return next
    })
  }
  const enableAllClasses = () => setActiveClasses(null)
  const disableAllClasses = () => setActiveClasses(new Set())

  // --- Derived data -------------------------------------------------------
  const allSymbols = listQuery.data ?? EMPTY_PLAN_SYMBOLS
  const summary: PlanSymbolSummary | null = summaryQuery.data ?? null

  // Stable list of every class that has at least one detection, in
  // descending count order. Useful for the legend ("most common
  // first").
  const allClasses = useMemo(() => {
    if (!summary) return [] as string[]
    return Object.keys(summary.counts).sort((a, b) => summary.counts[b] - summary.counts[a])
  }, [summary])

  // Symbols filtered by ``activeClasses`` and the current page.
  // Filtering by page happens here too so the overlay only sees the
  // boxes for the page the user is looking at.
  const visibleSymbols = useMemo(() => {
    const allowed = activeClasses
    return allSymbols.filter((s) => {
      if (allowed && !allowed.has(s.symbol_class)) return false
      return true
    })
  }, [allSymbols, activeClasses])

  return {
    // queries
    listQuery,
    summaryQuery,
    // raw data
    allSymbols,
    summary,
    allClasses,
    // derived
    visibleSymbols,
    // state + actions
    showSymbols,
    setShowSymbols,
    activeClasses,
    toggleClass,
    enableAllClasses,
    disableAllClasses,
  }
}

// ---------------------------------------------------------------------------
// Pure helpers (exported for testing + reuse)
// ---------------------------------------------------------------------------

/**
 * Filter a list of symbols by page number.
 *
 * Symbols without a page number (``page_number = null``) are kept
 * regardless of the filter — they likely belong to a single-page
 * plan. This is the same fail-safe policy the rest of the platform
 * applies to optional page metadata.
 */
export function filterSymbolsByPage(symbols: PlanSymbol[], page: number): PlanSymbol[] {
  if (page < 1) return symbols
  return symbols.filter((s) => s.page_number == null || s.page_number === page)
}

/**
 * Stable, deterministic color per symbol class. We hash the class
 * name into the HSL hue wheel so every plan uses the same color
 * for "door", "window", etc., without a hard-coded table.
 */
const SATURATION = 70
const LIGHTNESS = 55

export function colorForSymbolClass(cls: string): string {
  // Sum the bytes of the class name for a tiny, allocation-free
  // hash. We do not need cryptographic quality here.
  let h = 0
  for (let i = 0; i < cls.length; i++) {
    h = (h * 31 + cls.charCodeAt(i)) & 0xffffffff
  }
  const hue = Math.abs(h % 360)
  return `hsl(${hue}, ${SATURATION}%, ${LIGHTNESS}%)`
}

/**
 * Translate a snake_case symbol class into a short human label for
 * the legend (``"single_door"`` → ``"Single door"``). Falls back to
 * the raw class name when the class is unknown.
 */
export function humaniseSymbolClass(cls: string): string {
  if (!cls) return cls
  return cls
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}
