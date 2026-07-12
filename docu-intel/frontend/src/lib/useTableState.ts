import { useCallback, useEffect, useState } from "react"

interface TableState {
  sort?: { id: string; desc: boolean }
  pagination?: { pageIndex: number; pageSize: number }
  filters?: Record<string, string>
  columnVisibility?: Record<string, boolean>
}

/**
 * Persists table state (sort, pagination, filters) to localStorage.
 * Automatically restores on mount and saves on change.
 */
export function useTableState(tableId: string, initialState?: TableState) {
  const storageKey = `docu-intel:table:${tableId}`

  const [state, setState] = useState<TableState>(() => {
    try {
      const saved = localStorage.getItem(storageKey)
      if (saved) return { ...initialState, ...JSON.parse(saved) }
    } catch {
      // Ignore unavailable or malformed persisted state.
    }
    return initialState ?? {}
  })

  // Save to localStorage on change
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(state))
    } catch {
      // Persistence is best-effort.
    }
  }, [storageKey, state])

  const setSort = useCallback((sort: TableState["sort"]) => {
    setState((prev) => ({ ...prev, sort }))
  }, [])

  const setPagination = useCallback((pagination: TableState["pagination"]) => {
    setState((prev) => ({ ...prev, pagination }))
  }, [])

  const setFilters = useCallback((filters: Record<string, string>) => {
    setState((prev) => ({
      ...prev,
      filters,
      pagination: prev.pagination
        ? { pageIndex: 0, pageSize: prev.pagination.pageSize }
        : undefined,
    }))
  }, [])

  const setFilter = useCallback((key: string, value: string) => {
    setState((prev) => ({
      ...prev,
      filters: { ...prev.filters, [key]: value },
      pagination: prev.pagination
        ? { pageIndex: 0, pageSize: prev.pagination.pageSize }
        : undefined,
    }))
  }, [])

  const clearFilters = useCallback(() => {
    setState((prev) => ({
      ...prev,
      filters: {},
      pagination: prev.pagination
        ? { pageIndex: 0, pageSize: prev.pagination.pageSize }
        : undefined,
    }))
  }, [])

  const setColumnVisibility = useCallback((visibility: Record<string, boolean>) => {
    setState((prev) => ({ ...prev, columnVisibility: visibility }))
  }, [])

  const reset = useCallback(() => {
    setState(initialState ?? {})
    try { localStorage.removeItem(storageKey) } catch {
      // Persistence is best-effort.
    }
  }, [storageKey, initialState])

  return {
    ...state,
    setSort,
    setPagination,
    setFilters,
    setFilter,
    clearFilters,
    setColumnVisibility,
    reset,
  }
}
