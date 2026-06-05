import { FormEvent, useEffect, useMemo, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Bookmark,
  Download,
  ExternalLink,
  FileSearch,
  FileText,
  Filter,
  MessageCircle,
  Search,
  Star,
  X,
} from "lucide-react"

import { api } from "@/api/client"
import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { EmptyState } from "@/components/layout/EmptyState"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { notify } from "@/lib/toast"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import type { SearchResult } from "@/types/api"

// ---------------------------------------------------------------------------
// Search mode definitions
// ---------------------------------------------------------------------------
type SearchMode = "hybrid" | "text" | "semantic" | "guided:budget" | "guided:order" | "guided:reference" | "guided:client" | "guided:supplier"

const searchModes: { id: SearchMode; label: string; desc: string }[] = [
  { id: "hybrid", label: "Híbrida", desc: "Mejor resultado combinando texto y significado" },
  { id: "text", label: "Textual", desc: "Coincidencia exacta de palabras" },
  { id: "semantic", label: "Semántica", desc: "Búsqueda por significado" },
  { id: "guided:budget", label: "Presupuesto", desc: "Buscar por número de presupuesto" },
  { id: "guided:order", label: "Pedido", desc: "Buscar por número de pedido" },
  { id: "guided:reference", label: "Referencia", desc: "Buscar por referencia" },
  { id: "guided:client", label: "Cliente", desc: "Buscar por nombre de cliente" },
  { id: "guided:supplier", label: "Proveedor", desc: "Buscar por nombre de proveedor" },
]

const typeOptions = ["", "presupuesto", "pedido", "factura", "plano", "imagen", "excel", "otro"]
const statusOptions = ["", "processed", "needs_review", "failed", "pending", "duplicate"]

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export function SearchPage() {
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

  const activeFilters = useMemo(() => {
    const f: string[] = []
    if (filterType) f.push(`tipo: ${filterType}`)
    if (filterStatus) f.push(`estado: ${filterStatus}`)
    if (filterSupplier) f.push(`proveedor: ${filterSupplier}`)
    if (filterClient) f.push(`cliente: ${filterClient}`)
    if (filterMinConf) f.push(`confianza ≥${filterMinConf}%`)
    if (filterSourcePath) f.push(`carpeta: ${filterSourcePath}`)
    if (filterDateFrom) f.push(`desde: ${filterDateFrom}`)
    if (filterDateTo) f.push(`hasta: ${filterDateTo}`)
    return f
  }, [filterType, filterStatus, filterSupplier, filterClient, filterMinConf, filterSourcePath, filterDateFrom, filterDateTo])

  const savedSearches = useQuery({ queryKey: ["saved-searches"], queryFn: api.savedSearches })
  const results = useQuery({
    queryKey: ["search", mode, submitted],
    queryFn: () => runSearch(mode, submitted),
    enabled: submitted.length > 0,
  })
  const saveSearch = useMutation({
    mutationFn: () => api.createSavedSearch({ name: savedName.trim() || submitted, query: submitted, mode, filters_json: {} }),
    onSuccess: () => {
      setSavedName("")
      queryClient.invalidateQueries({ queryKey: ["saved-searches"] })
      notify.success("Búsqueda guardada")
    },
    onError: (err) => notify.error(err, "No se pudo guardar la búsqueda"),
  })

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

  // Client-side filtering
  const filteredResults = useMemo(() => {
    let items = results.data ?? []
    if (filterType) items = items.filter((r) => r.document_type === filterType)
    if (filterStatus) items = items.filter((r) => r.status === filterStatus)
    if (filterMinConf) {
      const min = Number(filterMinConf) / 100
      items = items.filter((r) => r.ocr_confidence != null && r.ocr_confidence >= min)
    }
    return items
  }, [results.data, filterType, filterStatus, filterMinConf])

  function clearFilters() {
    setFilterType(""); setFilterStatus(""); setFilterSupplier(""); setFilterClient("")
    setFilterMinConf(""); setFilterSourcePath(""); setFilterDateFrom(""); setFilterDateTo("")
  }

  function goToChat(result: SearchResult) {
    const q = encodeURIComponent(`¿Qué dice el documento "${result.original_filename}" sobre esto?`)
    window.open(`/chat?q=${q}`, "_blank")
  }

  return (
    <>
      <Breadcrumbs items={[{ label: "Buscar" }]} />
      <PageHeader title="Buscar" description="Encuentra documentos por texto, significado o referencia exacta. Usa filtros para afinar resultados." />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        {/* Main */}
        <div className="space-y-4">
          <Card>
            <CardContent className="space-y-3 pt-4">
              {/* Mode selector */}
              <div className="flex flex-wrap gap-1 rounded-md border bg-muted p-1">
                {searchModes.slice(0, 4).map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={cn(
                      "rounded px-3 py-1.5 text-xs font-medium transition-colors",
                      item.id === mode ? "bg-background shadow-sm text-[var(--text-primary)]" : "text-[var(--text-muted)] hover:text-[var(--text-primary)]",
                    )}
                    onClick={() => setMode(item.id)}
                    title={item.desc}
                  >
                    {item.label}
                  </button>
                ))}
                <span className="mx-1 w-px bg-[var(--border)]" />
                {searchModes.slice(4).map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={cn(
                      "rounded px-3 py-1.5 text-xs font-medium transition-colors",
                      item.id === mode ? "bg-background shadow-sm text-[var(--text-primary)]" : "text-[var(--text-muted)] hover:text-[var(--text-primary)]",
                    )}
                    onClick={() => setMode(item.id)}
                    title={item.desc}
                  >
                    {item.label}
                  </button>
                ))}
              </div>

              {/* Search input */}
              <form className="flex gap-2" onSubmit={onSubmit}>
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Ej. factura enero 2026, pedido 154, proveedor Suministros SA..."
                  className="h-9 flex-1"
                />
                <Button disabled={!query.trim()} className="h-9 gap-1.5">
                  <Search className="h-4 w-4" />
                  Buscar
                </Button>
              </form>

              {/* Filter toggle + active filters */}
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant={showFilters || activeFilters.length > 0 ? "default" : "outline"}
                  size="sm"
                  className="h-7 text-xs gap-1"
                  onClick={() => setShowFilters(!showFilters)}
                >
                  <Filter className="h-3 w-3" />
                  Filtros
                  {activeFilters.length > 0 && (
                    <Badge variant="info" className="ml-1 text-[10px] px-1 py-0">{activeFilters.length}</Badge>
                  )}
                </Button>
                {activeFilters.map((f, i) => (
                  <Badge key={i} variant="outline" className="text-[10px] gap-1 pr-1">
                    {f}
                    <button onClick={() => clearFilters()} className="ml-0.5 hover:text-[var(--rose)]"><X className="h-2.5 w-2.5" /></button>
                  </Badge>
                ))}
                {activeFilters.length > 1 && (
                  <Button variant="ghost" size="sm" className="h-7 text-xs text-[var(--text-muted)]" onClick={clearFilters}>
                    Limpiar todo
                  </Button>
                )}
              </div>

              {/* Filter panel */}
              {showFilters && (
                <div className="grid gap-2 rounded-md border bg-slate-50 p-3 sm:grid-cols-2 lg:grid-cols-4">
                  <FilterField label="Tipo documental" value={filterType} onChange={setFilterType} options={typeOptions} />
                  <FilterField label="Estado" value={filterStatus} onChange={setFilterStatus} options={statusOptions} />
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold uppercase text-[var(--text-muted)]">Proveedor</label>
                    <Input className="h-8 text-xs" value={filterSupplier} onChange={(e) => setFilterSupplier(e.target.value)} placeholder="Nombre proveedor..." />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold uppercase text-[var(--text-muted)]">Cliente</label>
                    <Input className="h-8 text-xs" value={filterClient} onChange={(e) => setFilterClient(e.target.value)} placeholder="Nombre cliente..." />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold uppercase text-[var(--text-muted)]">Confianza OCR mín. (%)</label>
                    <Input className="h-8 text-xs" type="number" min="0" max="100" value={filterMinConf} onChange={(e) => setFilterMinConf(e.target.value)} placeholder="Ej. 80" />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold uppercase text-[var(--text-muted)]">Carpeta contiene</label>
                    <Input className="h-8 text-xs" value={filterSourcePath} onChange={(e) => setFilterSourcePath(e.target.value)} placeholder="presupuestos/2026..." />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold uppercase text-[var(--text-muted)]">Desde fecha</label>
                    <Input className="h-8 text-xs" type="date" value={filterDateFrom} onChange={(e) => setFilterDateFrom(e.target.value)} />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] font-semibold uppercase text-[var(--text-muted)]">Hasta fecha</label>
                    <Input className="h-8 text-xs" type="date" value={filterDateTo} onChange={(e) => setFilterDateTo(e.target.value)} />
                  </div>
                </div>
              )}

              {/* Save search */}
              {submitted && (
                <div className="flex gap-2">
                  <Input className="h-8 text-xs" value={savedName} onChange={(e) => setSavedName(e.target.value)} placeholder="Guardar búsqueda como..." />
                  <Button variant="outline" size="sm" className="h-8 text-xs gap-1" onClick={() => saveSearch.mutate()} disabled={saveSearch.isPending || !submitted}>
                    <Star className="h-3 w-3" />
                    Guardar
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Export buttons */}
          {submitted && results.data && results.data.length > 0 && (
            <div className="flex gap-2">
              <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={() => api.exportSearchCSV(submitted)}>
                <Download className="h-3 w-3" /> Exportar CSV
              </Button>
            </div>
          )}

          {/* Results */}
          {submitted && (
            <div className="space-y-3">
              {results.isLoading && (
                <Card><CardContent className="py-8 text-center text-sm text-[var(--text-muted)]">Buscando...</CardContent></Card>
              )}
              {!results.isLoading && filteredResults.length === 0 && (
                <Card>
                  <CardContent className="py-8">
                    <EmptyState
                      title="Sin resultados"
                      description={results.data?.length ? `${results.data.length} resultados filtrados. Prueba a quitar filtros o cambiar el modo de búsqueda.` : "No se encontraron documentos con ese criterio. Prueba con otros términos o cambia el modo de búsqueda."}
                      icon={<FileSearch className="h-8 w-8" />}
                    />
                  </CardContent>
                </Card>
              )}
              {filteredResults.map((result, index) => (
                <SearchResultCard key={`${result.document_id}-${result.page_number ?? "p"}-${result.block_id ?? "b"}-${index}`} result={result} onAskAbout={goToChat} />
              ))}
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px] font-semibold flex items-center gap-2">
                <Star className="h-4 w-4 text-[var(--amber)]" />
                Búsquedas guardadas
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {(savedSearches.data ?? []).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="w-full rounded-md border p-2.5 text-left text-sm hover:bg-slate-50 transition-colors"
                  onClick={() => {
                    setQuery(item.query)
                    setSubmitted(item.query)
                    setMode(toSearchMode(item.mode))
                  }}
                >
                  <span className="flex items-center gap-2 font-medium text-[13px]">
                    <Bookmark className="h-3.5 w-3.5 text-[var(--primary)]" />
                    {item.name}
                  </span>
                  <span className="mt-1 block truncate text-xs text-[var(--text-muted)]">{item.query}</span>
                </button>
              ))}
              {!savedSearches.data?.length && (
                <p className="text-sm text-[var(--text-muted)]">Sin búsquedas guardadas.</p>
              )}
            </CardContent>
          </Card>

          {/* Tips */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px] font-semibold">Consejos</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-[var(--text-secondary)]">
              <p>· Usa <strong>Híbrida</strong> para búsquedas generales.</p>
              <p>· Usa <strong>Textual</strong> cuando busques palabras exactas.</p>
              <p>· Usa <strong>Semántica</strong> para encontrar conceptos similares.</p>
              <p>· Los modos <strong>Presupuesto/Pedido</strong> buscan por número exacto.</p>
              <p>· Añade filtros para afinar resultados por tipo, estado o confianza.</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Search result card
// ---------------------------------------------------------------------------
function SearchResultCard({ result, onAskAbout }: { result: SearchResult; onAskAbout: (r: SearchResult) => void }) {
  const matchReason = getMatchReason(result)

  return (
    <Card className="group transition-all hover:shadow-sm">
      <CardHeader className="flex-row items-start justify-between gap-3 pb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 flex-shrink-0 text-[var(--text-muted)]" />
            <Link to={`/documents/${result.document_id}`} className="text-[14px] font-semibold text-[var(--text-primary)] hover:text-[var(--primary)] truncate">
              {result.original_filename}
            </Link>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <Badge variant="neutral" className="text-[10px] capitalize">{result.document_type}</Badge>
            <StatusBadge status={result.status} />
            {result.page_number != null && (
              <span className="text-[11px] text-[var(--text-muted)]">Pág. {result.page_number}</span>
            )}
            <ConfidenceBadge value={result.ocr_confidence} showLabel />
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          <ScoreBadge label={modeLabel(result.source_type)} value={result.score} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {/* Match reason */}
        {matchReason && (
          <p className="text-[11px] text-[var(--text-muted)] italic">{matchReason}</p>
        )}

        {/* Excerpt */}
        <p className="rounded-md bg-slate-50 p-3 text-[13px] leading-6 text-[var(--text-secondary)]">
          {result.excerpt || "Sin extracto disponible."}
        </p>

        {/* Actions */}
        <div className="flex flex-wrap gap-1.5">
          <Button asChild variant="outline" size="sm" className="h-7 text-xs gap-1">
            <Link to={`/documents/${result.document_id}`}>
              <ExternalLink className="h-3 w-3" />
              Abrir documento
            </Link>
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs gap-1"
            onClick={() => onAskAbout(result)}
          >
            <MessageCircle className="h-3 w-3" />
            Preguntar sobre este documento
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Score badge
// ---------------------------------------------------------------------------
function ScoreBadge({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100)
  const tone = pct >= 80 ? "emerald" : pct >= 60 ? "amber" : "rose"
  return (
    <span className={cn(
      "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
      tone === "emerald" && "bg-[var(--emerald-light)] text-[#065F46]",
      tone === "amber" && "bg-[var(--amber-light)] text-[#92400E]",
      tone === "rose" && "bg-[var(--rose-light)] text-[#9F1239]",
    )}>
      {label}: {pct}%
    </span>
  )
}

// ---------------------------------------------------------------------------
// Filter field
// ---------------------------------------------------------------------------
function FilterField({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <div className="space-y-1">
      <label className="text-[10px] font-semibold uppercase text-[var(--text-muted)]">{label}</label>
      <select className="h-8 w-full rounded-md border bg-white px-2 text-xs" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((opt) => (
          <option key={opt} value={opt}>{opt || "—"}</option>
        ))}
      </select>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function getMatchReason(result: SearchResult): string {
  const reasons: string[] = []
  if (result.source_type === "text") reasons.push("Coincidencia textual exacta")
  if (result.source_type === "semantic") reasons.push("Similitud semántica")
  if (result.source_type === "hybrid") reasons.push("Coincidencia combinada (texto + significado)")
  if (result.source_type === "guided") reasons.push("Búsqueda guiada por campo exacto")
  if (result.ocr_confidence != null && result.ocr_confidence < 0.7) reasons.push("OCR de baja confianza — verificar manualmente")
  return reasons.join(" · ")
}

function modeLabel(sourceType: string): string {
  if (sourceType === "text") return "Textual"
  if (sourceType === "semantic") return "Semántico"
  if (sourceType === "hybrid") return "Híbrido"
  if (sourceType === "guided") return "Exacto"
  return "Score"
}

function runSearch(mode: SearchMode, query: string) {
  if (mode === "semantic") return api.semanticSearch(query)
  if (mode === "hybrid") return api.hybridSearch(query)
  if (mode.startsWith("guided:")) return api.guidedSearch(query, mode.replace("guided:", ""))
  return api.textSearch(query)
}

function toSearchMode(value: string): SearchMode {
  return searchModes.some((item) => item.id === value) ? (value as SearchMode) : "hybrid"
}
