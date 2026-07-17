import { useEffect, useMemo, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useSearchParams } from "react-router-dom"

import { api } from "@/api/client"
import { notify } from "@/lib/toast"
import { DOCUMENT_TYPE_VALUES } from "@/lib/documentTypes"
import type { SearchResult } from "@/types/api"

// ---------------------------------------------------------------------------
// F8b-cont5 - search hook
// ---------------------------------------------------------------------------
// Owns the seven filters, the search input, the search mode, the
// saved-searches query, the search query (text/semantic/hybrid/
// guided:*) and the save-search mutation. Returns the derived
// ``filteredResults`` (client-side post-filter) and the
// ``activeFilters`` (label list) the UI renders as badges.
// ---------------------------------------------------------------------------

export type SearchMode =
  | "hybrid"
  | "text"
  | "semantic"
  | "guided:budget"
  | "guided:order"
  | "guided:reference"
  | "guided:client"
  | "guided:supplier"

export const SEARCH_MODES: ReadonlyArray<{
  id: SearchMode
  label: string
  desc: string
}> = [
  { id: "hybrid", label: "Híbrida", desc: "Mejor resultado combinando texto y significado" },
  { id: "text", label: "Textual", desc: "Coincidencia exacta de palabras" },
  { id: "semantic", label: "Semántica", desc: "Búsqueda por significado" },
  { id: "guided:budget", label: "Presupuesto", desc: "Buscar por número de presupuesto" },
  { id: "guided:order", label: "Pedido", desc: "Buscar por número de pedido" },
  { id: "guided:reference", label: "Referencia", desc: "Buscar por referencia" },
  { id: "guided:client", label: "Cliente", desc: "Buscar por nombre de cliente" },
  { id: "guided:supplier", label: "Proveedor", desc: "Buscar por nombre de proveedor" },
] as const

export const TYPE_OPTIONS = DOCUMENT_TYPE_VALUES

export const STATUS_OPTIONS = ["", "processed", "needs_review", "failed", "pending", "duplicate"]

/** Pick the right API method for the selected mode. Pure function. */
export function runSearch(mode: SearchMode, query: string): Promise<SearchResult[]> {
  if (mode === "semantic") return api.semanticSearch(query)
  if (mode === "hybrid") return api.hybridSearch(query)
  if (mode.startsWith("guided:")) return api.guidedSearch(query, mode.replace("guided:", ""))
  return api.textSearch(query)
}

/** Coerce a free string back to a known SearchMode (falls back to hybrid). */
export function toSearchMode(value: string): SearchMode {
  return (SEARCH_MODES as ReadonlyArray<{ id: string }>).some((item) => item.id === value)
    ? (value as SearchMode)
    : "hybrid"
}

/** Format a result's source_type as a human label. Pure function. */
export function modeLabel(sourceType: string): string {
  if (sourceType === "text") return "Textual"
  if (sourceType === "semantic") return "Semántico"
  if (sourceType === "hybrid") return "Híbrido"
  if (sourceType === "guided") return "Exacto"
  return "Score"
}

/** Build the "why did this match" string the search result card shows. */
export function getMatchReason(result: SearchResult): string {
  const reasons: string[] = []
  if (result.source_type === "text") reasons.push("Coincidencia textual exacta")
  if (result.source_type === "semantic") reasons.push("Similitud semántica")
  if (result.source_type === "hybrid") reasons.push("Coincidencia combinada (texto + significado)")
  if (result.source_type === "guided") reasons.push("Búsqueda guiada por campo exacto")
  if (result.ocr_confidence != null && result.ocr_confidence < 0.7)
    reasons.push("OCR de baja confianza — verificar manualmente")
  return reasons.join(" · ")
}

/** Client-side filter applied on top of the search response. */
export function clientFilter(
  results: SearchResult[],
  filters: {
    type?: string
    status?: string
    minConfidencePercent?: string
  },
): SearchResult[] {
  let items = results
  if (filters.type) items = items.filter((r) => r.document_type === filters.type)
  if (filters.status) items = items.filter((r) => r.status === filters.status)
  if (filters.minConfidencePercent) {
    const min = Number(filters.minConfidencePercent) / 100
    items = items.filter((r) => r.ocr_confidence != null && r.ocr_confidence >= min)
  }
  return items
}

/** Build the active-filter labels the page renders as Badge chips. */
export function buildActiveFilters(filters: {
  type: string
  status: string
  supplier: string
  client: string
  minConfidencePercent: string
  sourcePath: string
  dateFrom: string
  dateTo: string
}): string[] {
  const f: string[] = []
  if (filters.type) f.push(`tipo: ${filters.type}`)
  if (filters.status) f.push(`estado: ${filters.status}`)
  if (filters.supplier) f.push(`proveedor: ${filters.supplier}`)
  if (filters.client) f.push(`cliente: ${filters.client}`)
  if (filters.minConfidencePercent) f.push(`confianza ≥${filters.minConfidencePercent}%`)
  if (filters.sourcePath) f.push(`carpeta: ${filters.sourcePath}`)
  if (filters.dateFrom) f.push(`desde: ${filters.dateFrom}`)
  if (filters.dateTo) f.push(`hasta: ${filters.dateTo}`)
  return f
}

export function useSearchPage() {
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const [query, setQuery] = useState("")
  const [submitted, setSubmitted] = useState("")
  const [mode, setMode] = useState<SearchMode>("hybrid")
  const [savedName, setSavedName] = useState("")
  const [showFilters, setShowFilters] = useState(false)

  // Filters
  const [filterType, setFilterType] = useState("")
  const [filterStatus, setFilterStatus] = useState("")
  const [filterSupplier, setFilterSupplier] = useState("")
  const [filterClient, setFilterClient] = useState("")
  const [filterMinConf, setFilterMinConf] = useState("")
  const [filterSourcePath, setFilterSourcePath] = useState("")
  const [filterDateFrom, setFilterDateFrom] = useState("")
  const [filterDateTo, setFilterDateTo] = useState("")

  const activeFilters = useMemo(
    () =>
      buildActiveFilters({
        type: filterType,
        status: filterStatus,
        supplier: filterSupplier,
        client: filterClient,
        minConfidencePercent: filterMinConf,
        sourcePath: filterSourcePath,
        dateFrom: filterDateFrom,
        dateTo: filterDateTo,
      }),
    [
      filterType,
      filterStatus,
      filterSupplier,
      filterClient,
      filterMinConf,
      filterSourcePath,
      filterDateFrom,
      filterDateTo,
    ],
  )

  const savedSearches = useQuery({
    queryKey: ["saved-searches"],
    queryFn: api.savedSearches,
  })
  const results = useQuery({
    queryKey: ["search", mode, submitted],
    queryFn: () => runSearch(mode, submitted),
    enabled: submitted.length > 0,
  })
  const saveSearch = useMutation({
    mutationFn: () =>
      api.createSavedSearch({
        name: savedName.trim() || submitted,
        query: submitted,
        mode,
        filters_json: {},
      }),
    onSuccess: () => {
      setSavedName("")
      queryClient.invalidateQueries({ queryKey: ["saved-searches"] })
      notify.success("Búsqueda guardada")
    },
    onError: (err) => notify.error(err, "No se pudo guardar la búsqueda"),
  })

  // Hydrate from ?q= on first render so deeplinks work
  useEffect(() => {
    const urlQuery = searchParams.get("q")?.trim()
    if (urlQuery) {
      setQuery(urlQuery)
      setSubmitted(urlQuery)
    }
  }, [searchParams])

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitted(query.trim())
  }

  const filteredResults = useMemo(
    () =>
      clientFilter(results.data ?? [], {
        type: filterType,
        status: filterStatus,
        minConfidencePercent: filterMinConf,
      }),
    [results.data, filterType, filterStatus, filterMinConf],
  )

  function clearFilters() {
    setFilterType("")
    setFilterStatus("")
    setFilterSupplier("")
    setFilterClient("")
    setFilterMinConf("")
    setFilterSourcePath("")
    setFilterDateFrom("")
    setFilterDateTo("")
  }

  function goToChat(result: SearchResult) {
    const q = encodeURIComponent(`¿Qué dice el documento "${result.original_filename}" sobre esto?`)
    window.open(`/chat?q=${q}`, "_blank")
  }

  return {
    // state
    query,
    setQuery,
    submitted,
    setSubmitted,
    mode,
    setMode,
    savedName,
    setSavedName,
    showFilters,
    setShowFilters,
    filterType,
    setFilterType,
    filterStatus,
    setFilterStatus,
    filterSupplier,
    setFilterSupplier,
    filterClient,
    setFilterClient,
    filterMinConf,
    setFilterMinConf,
    filterSourcePath,
    setFilterSourcePath,
    filterDateFrom,
    setFilterDateFrom,
    filterDateTo,
    setFilterDateTo,
    // queries
    savedSearches,
    results,
    // mutations
    saveSearch,
    // derived
    activeFilters,
    filteredResults,
    // actions
    onSubmit,
    clearFilters,
    goToChat,
  }
}

export type SearchPage = ReturnType<typeof useSearchPage>
