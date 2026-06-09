import { type FormEvent } from "react"
import { Link } from "react-router-dom"
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
  type LucideIcon,
} from "lucide-react"

import { api } from "@/api/client"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { EmptyState } from "@/components/layout/EmptyState"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import type { SearchResult } from "@/types/api"

import {
  getMatchReason,
  modeLabel,
  SEARCH_MODES,
  STATUS_OPTIONS,
  toSearchMode,
  TYPE_OPTIONS,
  type SearchMode,
} from "./useSearchPage"

// ---------------------------------------------------------------------------
// Breadcrumbs wrapper
// ---------------------------------------------------------------------------
export function SearchBreadcrumbs() {
  return <Breadcrumbs items={[{ label: "Buscar" }]} />
}

// ---------------------------------------------------------------------------
// ModeSelector
// ---------------------------------------------------------------------------
export function ModeSelector({
  mode,
  setMode,
}: {
  mode: SearchMode
  setMode: (m: SearchMode) => void
}) {
  return (
    <div className="flex flex-wrap gap-1 rounded-md border bg-muted p-1">
      {SEARCH_MODES.slice(0, 4).map((item) => (
        <ModeButton key={item.id} active={mode === item.id} onClick={() => setMode(item.id)} title={item.desc}>
          {item.label}
        </ModeButton>
      ))}
      <span className="mx-1 w-px bg-[var(--border)]" />
      {SEARCH_MODES.slice(4).map((item) => (
        <ModeButton key={item.id} active={mode === item.id} onClick={() => setMode(item.id)} title={item.desc}>
          {item.label}
        </ModeButton>
      ))}
    </div>
  )
}

function ModeButton({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean
  onClick: () => void
  title: string
  children: React.ReactNode
}) {
  return (
    <button
      key={undefined}
      type="button"
      className={cn(
        "rounded px-3 py-1.5 text-xs font-medium transition-colors",
        active
          ? "bg-background text-[var(--text-primary)] shadow-sm"
          : "text-[var(--text-muted)] hover:text-[var(--text-primary)]",
      )}
      onClick={onClick}
      title={title}
    >
      {children}
    </button>
  )
}

// ---------------------------------------------------------------------------
// SearchInputBar
// ---------------------------------------------------------------------------
export function SearchInputBar({
  query,
  setQuery,
  onSubmit,
}: {
  query: string
  setQuery: (v: string) => void
  onSubmit: (e: FormEvent) => void
}) {
  return (
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
  )
}

// ---------------------------------------------------------------------------
// ActiveFiltersBar
// ---------------------------------------------------------------------------
export function ActiveFiltersBar({
  showFilters,
  setShowFilters,
  activeFilters,
  onClear,
  onClearAll,
}: {
  showFilters: boolean
  setShowFilters: (v: boolean) => void
  activeFilters: string[]
  onClear: () => void
  onClearAll: () => void
}) {
  return (
    <div className="flex items-center gap-2">
      <Button
        type="button"
        variant={showFilters || activeFilters.length > 0 ? "default" : "outline"}
        size="sm"
        className="h-7 gap-1 text-xs"
        onClick={() => setShowFilters(!showFilters)}
      >
        <Filter className="h-3 w-3" />
        Filtros
        {activeFilters.length > 0 && (
          <Badge variant="info" className="ml-1 px-1 py-0 text-[10px]">
            {activeFilters.length}
          </Badge>
        )}
      </Button>
      {activeFilters.map((f, i) => (
        <Badge key={i} variant="outline" className="gap-1 pr-1 text-[10px]">
          {f}
          <button onClick={onClear} className="ml-0.5 hover:text-[var(--rose)]">
            <X className="h-2.5 w-2.5" />
          </button>
        </Badge>
      ))}
      {activeFilters.length > 1 && (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 text-xs text-[var(--text-muted)]"
          onClick={onClearAll}
        >
          Limpiar todo
        </Button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// FilterPanel
// ---------------------------------------------------------------------------
export function FilterPanel({
  show,
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
}: {
  show: boolean
  filterType: string
  setFilterType: (v: string) => void
  filterStatus: string
  setFilterStatus: (v: string) => void
  filterSupplier: string
  setFilterSupplier: (v: string) => void
  filterClient: string
  setFilterClient: (v: string) => void
  filterMinConf: string
  setFilterMinConf: (v: string) => void
  filterSourcePath: string
  setFilterSourcePath: (v: string) => void
  filterDateFrom: string
  setFilterDateFrom: (v: string) => void
  filterDateTo: string
  setFilterDateTo: (v: string) => void
}) {
  if (!show) return null
  return (
    <div className="grid gap-2 rounded-md border bg-slate-50 p-3 sm:grid-cols-2 lg:grid-cols-4">
      <FilterSelect label="Tipo documental" value={filterType} onChange={setFilterType} options={TYPE_OPTIONS} />
      <FilterSelect label="Estado" value={filterStatus} onChange={setFilterStatus} options={STATUS_OPTIONS} />
      <FilterInput
        label="Proveedor"
        value={filterSupplier}
        onChange={setFilterSupplier}
        placeholder="Nombre proveedor..."
      />
      <FilterInput
        label="Cliente"
        value={filterClient}
        onChange={setFilterClient}
        placeholder="Nombre cliente..."
      />
      <FilterInput
        label="Confianza OCR mín. (%)"
        value={filterMinConf}
        onChange={setFilterMinConf}
        placeholder="Ej. 80"
        type="number"
      />
      <FilterInput
        label="Carpeta contiene"
        value={filterSourcePath}
        onChange={setFilterSourcePath}
        placeholder="presupuestos/2026..."
      />
      <FilterInput
        label="Desde fecha"
        value={filterDateFrom}
        onChange={setFilterDateFrom}
        type="date"
      />
      <FilterInput
        label="Hasta fecha"
        value={filterDateTo}
        onChange={setFilterDateTo}
        type="date"
      />
    </div>
  )
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: string[]
}) {
  return (
    <div className="space-y-1">
      <label className="text-[10px] font-semibold uppercase text-[var(--text-muted)]">{label}</label>
      <select
        className="h-8 w-full rounded-md border bg-white px-2 text-xs"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt || "—"}
          </option>
        ))}
      </select>
    </div>
  )
}

function FilterInput({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
}) {
  return (
    <div className="space-y-1">
      <label className="text-[10px] font-semibold uppercase text-[var(--text-muted)]">{label}</label>
      <Input
        className="h-8 text-xs"
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// SaveSearchBar
// ---------------------------------------------------------------------------
export function SaveSearchBar({
  visible,
  savedName,
  setSavedName,
  onSave,
  isPending,
}: {
  visible: boolean
  savedName: string
  setSavedName: (v: string) => void
  onSave: () => void
  isPending: boolean
}) {
  if (!visible) return null
  return (
    <div className="flex gap-2">
      <Input
        className="h-8 text-xs"
        value={savedName}
        onChange={(e) => setSavedName(e.target.value)}
        placeholder="Guardar búsqueda como..."
      />
      <Button
        variant="outline"
        size="sm"
        className="h-8 gap-1 text-xs"
        onClick={onSave}
        disabled={isPending}
      >
        <Star className="h-3 w-3" />
        Guardar
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ExportBar
// ---------------------------------------------------------------------------
export function ExportBar({ submitted, query }: { submitted: string; query: string }) {
  if (!submitted) return null
  return (
    <div className="flex gap-2">
      <Button
        variant="outline"
        size="sm"
        className="h-7 gap-1 text-xs"
        onClick={() => api.exportSearchCSV(query)}
      >
        <Download className="h-3 w-3" /> Exportar CSV
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ResultsList
// ---------------------------------------------------------------------------
export function ResultsList({
  submitted,
  isLoading,
  results,
  filteredResults,
  onAskAbout,
}: {
  submitted: string
  isLoading: boolean
  results: SearchResult[] | undefined
  filteredResults: SearchResult[]
  onAskAbout: (r: SearchResult) => void
}) {
  if (!submitted) return null
  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-[var(--text-muted)]">
          Buscando...
        </CardContent>
      </Card>
    )
  }
  if (filteredResults.length === 0) {
    return (
      <Card>
        <CardContent className="py-8">
          <EmptyState
            title="Sin resultados"
            description={
              results?.length
                ? `${results.length} resultados filtrados. Prueba a quitar filtros o cambiar el modo de búsqueda.`
                : "No se encontraron documentos con ese criterio. Prueba con otros términos o cambia el modo de búsqueda."
            }
            icon={<FileSearch className="h-8 w-8" />}
          />
        </CardContent>
      </Card>
    )
  }
  return (
    <div className="space-y-3">
      {filteredResults.map((result, index) => (
        <SearchResultCard
          key={`${result.document_id}-${result.page_number ?? "p"}-${result.block_id ?? "b"}-${index}`}
          result={result}
          onAskAbout={onAskAbout}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// SearchResultCard
// ---------------------------------------------------------------------------
export function SearchResultCard({
  result,
  onAskAbout,
}: {
  result: SearchResult
  onAskAbout: (r: SearchResult) => void
}) {
  const matchReason = getMatchReason(result)
  return (
    <Card className="group transition-all hover:shadow-sm">
      <CardHeader className="flex-row items-start justify-between gap-3 pb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <FileText className="h-4 w-4 flex-shrink-0 text-[var(--text-muted)]" />
            <Link
              to={`/documents/${result.document_id}`}
              className="truncate text-[14px] font-semibold text-[var(--text-primary)] hover:text-[var(--primary)]"
            >
              {result.original_filename}
            </Link>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <Badge variant="neutral" className="text-[10px] capitalize">
              {result.document_type}
            </Badge>
            <StatusBadge status={result.status} />
            {result.page_number != null && (
              <span className="text-[11px] text-[var(--text-muted)]">Pág. {result.page_number}</span>
            )}
            <ConfidenceBadge value={result.ocr_confidence} showLabel />
          </div>
        </div>
        <div className="flex flex-shrink-0 items-center gap-1.5">
          <ScoreBadge label={modeLabel(result.source_type)} value={result.score} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {matchReason && (
          <p className="text-[11px] italic text-[var(--text-muted)]">{matchReason}</p>
        )}
        <p className="rounded-md bg-slate-50 p-3 text-[13px] leading-6 text-[var(--text-secondary)]">
          {result.excerpt || "Sin extracto disponible."}
        </p>
        <div className="flex flex-wrap gap-1.5">
          <Button asChild variant="outline" size="sm" className="h-7 gap-1 text-xs">
            <Link to={`/documents/${result.document_id}`}>
              <ExternalLink className="h-3 w-3" />
              Abrir documento
            </Link>
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1 text-xs"
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
// ScoreBadge
// ---------------------------------------------------------------------------
export function ScoreBadge({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100)
  const tone = pct >= 80 ? "emerald" : pct >= 60 ? "amber" : "rose"
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
        tone === "emerald" && "bg-[var(--emerald-light)] text-[#065F46]",
        tone === "amber" && "bg-[var(--amber-light)] text-[#92400E]",
        tone === "rose" && "bg-[var(--rose-light)] text-[#9F1239]",
      )}
    >
      {label}: {pct}%
    </span>
  )
}

// ---------------------------------------------------------------------------
// Sidebar (right column)
// ---------------------------------------------------------------------------
export function SavedSearchesCard({
  savedSearches,
  onPick,
}: {
  savedSearches: { id: number; name: string; query: string; mode: string }[]
  onPick: (item: { query: string; mode: string }) => void
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-[14px] font-semibold">
          <Star className="h-4 w-4 text-[var(--amber)]" />
          Búsquedas guardadas
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {savedSearches.map((item) => (
          <button
            key={item.id}
            type="button"
            className="w-full rounded-md border p-2.5 text-left text-sm transition-colors hover:bg-slate-50"
            onClick={() => onPick({ query: item.query, mode: toSearchMode(item.mode) })}
          >
            <span className="flex items-center gap-2 text-[13px] font-medium">
              <Bookmark className="h-3.5 w-3.5 text-[var(--primary)]" />
              {item.name}
            </span>
            <span className="mt-1 block truncate text-xs text-[var(--text-muted)]">
              {item.query}
            </span>
          </button>
        ))}
        {!savedSearches.length && (
          <p className="text-sm text-[var(--text-muted)]">Sin búsquedas guardadas.</p>
        )}
      </CardContent>
    </Card>
  )
}

export function SearchTipsCard() {
  return (
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
  )
}

// Re-export the page header / breadcrumb helpers for the page itself
export { PageHeader }
export type { LucideIcon }
