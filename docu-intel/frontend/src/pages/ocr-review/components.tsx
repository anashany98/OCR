import { useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { Check, ExternalLink, FileText, RefreshCcw, RotateCw, Sparkles, X } from "lucide-react"

import { pageImageUrl } from "@/api/client"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn, formatDate } from "@/lib/utils"
import { DOCUMENT_TYPES } from "@/lib/documentTypes"

import { reviewKey, type OcrReviewData } from "./useOcrReviewPage"

type SelectedPage = NonNullable<OcrReviewData["data"]["selected"]>
type OcrBlock = SelectedPage["blocks"][number] | undefined

// ---------------------------------------------------------------------------
// F8 - OCR review page section components.
// F8b - Spaced: layout switched to 2-col (queue + details) with tabs
// inside the details panel. Quality flags and action bar redesigned
// for clarity.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// NeedsReembeddingBanner — compact banner shown only when there are
// docs needing re-embedding. Replaces the full table card from F8.
// ---------------------------------------------------------------------------
export function NeedsReembeddingBanner({ data }: { data: OcrReviewData }) {
  const { queries, mutations } = data
  const docs = queries.needsReembedding.data ?? []
  if (docs.length === 0) return null
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-amber-500/40 bg-amber-50/40 px-4 py-3 dark:bg-amber-950/20">
      <div className="flex items-start gap-3">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
        <div className="text-sm">
          <p className="font-medium text-amber-900 dark:text-amber-100">
            {docs.length} documento(s) con chunks sin embedding
          </p>
          <p className="text-xs text-amber-800/80 dark:text-amber-200/70">
            El provider de embeddings falló durante el procesamiento inicial. Regenera sin re-OCR.
          </p>
        </div>
      </div>
      <Button
        size="sm"
        variant="outline"
        onClick={() => mutations.reembed.mutate(docs[0].document_id)}
        disabled={mutations.reembed.isPending}
        title="Re-embebir el primer documento pendiente (luego continúa con el resto)"
      >
        <Sparkles data-icon="inline-start" />
        {mutations.reembed.isPending ? "Re-embediendo…" : `Re-embebir ${docs.length}`}
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// OcrReviewFilters — single row above the queue+details layout.
// Threshold as a number input, type and status as native selects (kept
// light, not over-styled).
// ---------------------------------------------------------------------------
export function OcrReviewFilters({ data }: { data: OcrReviewData }) {
  const { state, queries } = data
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-2">
        <label className="text-xs font-medium text-[var(--text-muted)]" htmlFor="ocr-threshold">
          Umbral OCR
        </label>
        <div className="relative">
          <Input
            id="ocr-threshold"
            type="number"
            min={0}
            max={100}
            step={5}
            value={state.thresholdPercent}
            onChange={(event) => state.setThresholdPercent(event.target.value)}
            className="h-8 w-20 pr-7 text-right tabular-nums"
          />
          <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-[var(--text-muted)]">
            %
          </span>
        </div>
      </div>
      <SelectPill
        value={state.documentType}
        onChange={state.setDocumentType}
        aria-label="Tipo de documento"
        options={DOCUMENT_TYPES}
      />
      <SelectPill
        value={state.statusFilter}
        onChange={state.setStatusFilter}
        aria-label="Estado de revisión"
        options={[
          { value: "", label: "Todos los estados" },
          { value: "needs_review", label: "Necesita revisión" },
          { value: "processed", label: "Procesado" },
          { value: "failed", label: "Fallido" },
        ]}
      />
      <Button
        variant="ghost"
        size="sm"
        onClick={() => queries.review.refetch()}
        disabled={queries.review.isFetching}
        title="Actualizar lista"
      >
        <RotateCw
          data-icon={queries.review.isFetching ? "inline-start" : undefined}
          className={cn(queries.review.isFetching && "animate-spin")}
        />
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// OcrReviewQueue — left column. Filenames truncated with tooltip showing
// the full path. Hover state and selected indicator.
// ---------------------------------------------------------------------------
export function OcrReviewQueue({ data }: { data: OcrReviewData }) {
  const { data: pageData, state } = data
  const items = pageData.reviewItems
  const threshold = state.threshold
  const selected = pageData.selected

  return (
    <Card className="overflow-hidden">
      <CardHeader className="border-b bg-muted/30 px-5 py-4">
        <div className="flex items-baseline justify-between gap-3">
          <CardTitle className="text-sm font-semibold uppercase tracking-wide">
            Cola de revisión
          </CardTitle>
          <span className="text-xs text-[var(--text-muted)] tabular-nums">
            {items.length} pág. · &lt;{Math.round(threshold * 100)}%
          </span>
        </div>
      </CardHeader>
      <div className="max-h-[640px] overflow-y-auto">
        {items.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
            <div className="rounded-full bg-muted p-3">
              <FileText className="h-5 w-5 text-[var(--text-muted)]" />
            </div>
            <p className="text-sm font-medium">No hay páginas bajo el umbral</p>
            <p className="text-xs text-[var(--text-muted)]">
              Sube el umbral o espera a que entren más documentos.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {items.map((item) => {
              const isSelected = selected && reviewKey(selected) === reviewKey(item)
              return (
                <li key={reviewKey(item)}>
                  <button
                    type="button"
                    onClick={() => state.setSelectedKey(reviewKey(item))}
                    className={cn(
                      "flex w-full items-start gap-3 px-5 py-3 text-left transition-colors",
                      "hover:bg-muted/50 focus:outline-none focus-visible:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring",
                      isSelected && "bg-[var(--accent-faint)] hover:bg-[var(--accent-faint)]",
                    )}
                    title={item.original_filename}
                  >
                    <div className="mt-0.5">
                      <ConfidenceDot value={item.ocr_confidence} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <p className="truncate text-sm font-medium">{item.original_filename}</p>
                        <span className="shrink-0 text-xs tabular-nums text-[var(--text-muted)]">
                          pág. {item.page_number}
                        </span>
                      </div>
                      <div className="mt-1 flex items-center gap-2">
                        <span className="text-[11px] uppercase tracking-wide text-[var(--text-muted)]">
                          {item.document_type}
                        </span>
                        <ReviewBadge status={item.review_status} />
                      </div>
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// OcrDetails — right column with sticky header + tabs (Preview / OCR / Blocks).
// ---------------------------------------------------------------------------
type DetailsTab = "preview" | "text" | "blocks" | "attempts"
export function OcrDetails({ data }: { data: OcrReviewData }) {
  const { data: pageData, state, mutations } = data
  const selected = pageData.selected
  const [tab, setTab] = useState<DetailsTab>("preview")

  if (!selected) {
    return (
      <Card className="flex h-full min-h-[400px] items-center justify-center">
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="rounded-full bg-muted p-4">
            <FileText className="h-6 w-6 text-[var(--text-muted)]" />
          </div>
          <p className="text-sm font-medium">Selecciona una página de la cola</p>
          <p className="text-xs text-[var(--text-muted)]">Para revisar OCR, aprobar o denegar.</p>
        </div>
      </Card>
    )
  }

  return (
    <Card className="flex flex-col overflow-hidden">
      {/* Header */}
      <CardHeader className="gap-3 border-b bg-muted/20 px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <CardTitle className="truncate text-base" title={selected.original_filename}>
              {selected.original_filename}
            </CardTitle>
            <CardDescription className="mt-1 flex items-center gap-3 text-xs">
              <span>Página {selected.page_number}</span>
              <span className="text-[var(--text-muted)]/60">·</span>
              <span className="tabular-nums">OCR {formatPercent(selected.ocr_confidence)}</span>
              {selected.ocr_calibrated_confidence != null && (
                <span className="tabular-nums">Verificada {formatPercent(selected.ocr_calibrated_confidence)}</span>
              )}
              <span className="text-[var(--text-muted)]/60">·</span>
              <span>{formatDate(selected.created_at)}</span>
            </CardDescription>
            <div className="mt-2 flex items-center gap-2">
              <StatusBadge status={selected.status} />
              <ReviewBadge status={selected.review_status} />
              {selected.quality_score != null && (
                <Badge variant="outline" className="tabular-nums">
                  Score {Math.round(selected.quality_score * 100)}%
                </Badge>
              )}
            </div>
          </div>
          <Button asChild variant="ghost" size="sm">
            <Link to={`/documents/${selected.document_id}`}>
              <ExternalLink data-icon="inline-start" />
              Abrir
            </Link>
          </Button>
        </div>

        {/* Primary action bar — Aprobar / Denegar (always visible) */}
        <div className="flex items-center gap-2 border-t pt-3">
          <Button
            className="flex-1"
            size="sm"
            disabled={mutations.review.isPending || selected.review_status === "approved"}
            onClick={() =>
              mutations.review.mutate({
                pageId: selected.page_id,
                reviewStatus: "approved",
                notes: state.reviewNotes,
              })
            }
          >
            <Check data-icon="inline-start" />
            Aprobar
          </Button>
          <Button
            className="flex-1"
            size="sm"
            variant="destructive"
            disabled={
              mutations.review.isPending ||
              selected.review_status === "rejected" ||
              !state.reviewNotes.trim()
            }
            onClick={() =>
              mutations.review.mutate({
                pageId: selected.page_id,
                reviewStatus: "rejected",
                notes: state.reviewNotes,
              })
            }
          >
            <X data-icon="inline-start" />
            Denegar
          </Button>
        </div>

        {/* Secondary actions — less prominent */}
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={mutations.reprocess.isPending}
            onClick={() => mutations.reprocess.mutate(selected.page_id)}
          >
            <RefreshCcw data-icon="inline-start" />
            Reprocesar OCR
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={mutations.reembed.isPending}
            onClick={() => mutations.reembed.mutate(selected.document_id)}
            title="Regenera los embeddings de todos los chunks del documento"
          >
            <Sparkles data-icon="inline-start" />
            Re-embebir documento
          </Button>
        </div>
      </CardHeader>

      {/* Notes + flags */}
      <div className="border-b bg-muted/10 px-6 py-4">
        <textarea
          className="w-full resize-none rounded-md border border-input bg-[var(--bg-canvas)] px-3 py-2 text-sm leading-relaxed placeholder:text-[var(--text-muted)]/60 focus:outline-none focus:ring-2 focus:ring-ring"
          rows={2}
          value={state.reviewNotes}
          onChange={(event) => state.setReviewNotes(event.target.value)}
          placeholder="Motivo o nota de revisión (obligatorio para denegar)"
        />
        {selected.quality_flags_json.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {selected.quality_flags_json.map((flag) => (
              <Badge key={flag} variant="warning" className="text-[10px]">
                {flag}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Tabs */}
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { value: "preview", label: "Preview", icon: <FileText className="h-3.5 w-3.5" /> },
          { value: "text", label: "Texto OCR", icon: <FileText className="h-3.5 w-3.5" /> },
          {
            value: "blocks",
            label: `Bloques (${selected.blocks?.length ?? 0})`,
            icon: <FileText className="h-3.5 w-3.5" />,
          },
          {
            value: "attempts",
            label: `Intentos (${selected.attempts?.length ?? 0})`,
            icon: <RefreshCcw className="h-3.5 w-3.5" />,
          },
        ]}
      />

      <CardContent className="flex-1 overflow-hidden p-0">
        {tab === "preview" && <PreviewPane selected={selected} />}
        {tab === "text" && <TextPane selected={selected} />}
        {tab === "blocks" && <BlocksPane selected={selected} />}
        {tab === "attempts" && <AttemptsPane selected={selected} />}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Detail panes (one per tab)
// ---------------------------------------------------------------------------

function PreviewPane({ selected }: { selected: SelectedPage }) {
  if (!selected.preview_url) {
    return (
      <div className="flex h-full min-h-[320px] items-center justify-center p-8 text-sm text-[var(--text-muted)]">
        No hay imagen de preview para esta página.
      </div>
    )
  }
  return (
    <div className="flex h-full min-h-[320px] items-center justify-center overflow-auto bg-muted p-4">
      <img
        alt={`Preview OCR página ${selected.page_number}`}
        className="max-h-[640px] w-full object-contain"
        src={pageImageUrl(selected.document_id, selected.page_number)}
      />
    </div>
  )
}

function TextPane({ selected }: { selected: SelectedPage }) {
  const text = selected.text?.trim()
  return (
    <div className="h-full max-h-[480px] overflow-auto p-5">
      {text ? (
        <pre className="whitespace-pre-wrap font-mono text-[13px] leading-relaxed text-foreground">
          {text}
        </pre>
      ) : (
        <div className="flex h-full min-h-[200px] items-center justify-center text-sm text-[var(--text-muted)]">
          Sin texto OCR disponible.
        </div>
      )}
    </div>
  )
}

function BlocksPane({ selected }: { selected: SelectedPage }) {
  const blocks: NonNullable<SelectedPage["blocks"]> = selected.blocks ?? []
  if (blocks.length === 0) {
    return (
      <div className="flex h-full min-h-[200px] items-center justify-center p-8 text-sm text-[var(--text-muted)]">
        No hay bloques OCR para esta página.
      </div>
    )
  }
  return (
    <div className="h-full max-h-[480px] overflow-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-32">Tipo</TableHead>
            <TableHead className="w-24">Confianza</TableHead>
            <TableHead>Texto</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {blocks.map((block) => (
            <TableRow key={block.id}>
              <TableCell>
                <Badge variant="outline" className="text-[10px]">
                  {block.block_type}
                </Badge>
              </TableCell>
              <TableCell>
                <ConfidenceDot value={block.confidence} withLabel />
              </TableCell>
              <TableCell className="max-w-[480px] whitespace-pre-wrap text-[13px]">
                {block.text ?? "-"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function AttemptsPane({ selected }: { selected: SelectedPage }) {
  const attempts = selected.attempts ?? []
  if (!attempts.length) {
    return <div className="p-6 text-sm text-[var(--text-muted)]">Sin historial de intentos para esta pÃ¡gina.</div>
  }
  return (
    <div className="h-full max-h-[480px] overflow-auto">
      <Table>
        <TableHeader><TableRow><TableHead>Motor</TableHead><TableHead>Confianza</TableHead><TableHead>Decisión</TableHead><TableHead>Texto</TableHead></TableRow></TableHeader>
        <TableBody>
          {attempts.map((attempt) => (
            <TableRow key={attempt.id} className={attempt.selected ? "bg-muted/40" : undefined}>
              <TableCell><Badge variant="outline">{attempt.engine}</Badge></TableCell>
              <TableCell>{formatPercent(attempt.calibrated_confidence ?? attempt.raw_confidence)}</TableCell>
              <TableCell>{attempt.decision ?? "pendiente"}</TableCell>
              <TableCell className="max-w-[360px] whitespace-pre-wrap text-xs">{attempt.text || attempt.error_message || "-"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared bits (confidence dot, review badge, tabs primitive, select pill)
// ---------------------------------------------------------------------------

function ConfidenceDot({ value, withLabel }: { value: number | null; withLabel?: boolean }) {
  if (value == null) {
    return (
      <span
        className="inline-flex h-2 w-2 rounded-full bg-muted-foreground/30"
        aria-label="Sin dato"
      />
    )
  }
  const tone = value < 0.5 ? "bg-red-500" : value < 0.7 ? "bg-amber-500" : "bg-emerald-500"
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full", tone)} aria-hidden="true" />
      {withLabel && (
        <span className="text-xs tabular-nums text-[var(--text-muted)]">
          {Math.round(value * 100)}%
        </span>
      )}
    </span>
  )
}

function ReviewBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    pending: "pendiente",
    approved: "aprobada",
    rejected: "denegada",
  }
  const variant =
    status === "approved" ? "success" : status === "rejected" ? "destructive" : "outline"
  return (
    <Badge variant={variant} className="text-[10px]">
      {labels[status] ?? status}
    </Badge>
  )
}

function SelectPill<T extends string>({
  value,
  onChange,
  options,
  ...rest
}: {
  value: T
  onChange: (next: T) => void
  options: { value: T; label: string }[]
} & Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange" | "children">) {
  return (
    <select
      {...rest}
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className="h-8 rounded-md border border-input bg-[var(--bg-canvas)] px-2.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  )
}

function Tabs<T extends string>({
  value,
  onChange,
  items,
}: {
  value: T
  onChange: (next: T) => void
  items: { value: T; label: string; icon?: ReactNode }[]
}) {
  return (
    <div className="flex border-b bg-[var(--bg-canvas)] px-6" role="tablist">
      {items.map((item) => {
        const active = item.value === value
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.value)}
            className={cn(
              "relative -mb-px flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors",
              active
                ? "border-[var(--accent)] text-foreground"
                : "border-transparent text-[var(--text-muted)] hover:text-foreground",
            )}
          >
            {item.icon}
            {item.label}
          </button>
        )
      })}
    </div>
  )
}

function formatPercent(value: number | null) {
  return value === null ? "-" : Math.round(value * 100) + "%"
}
