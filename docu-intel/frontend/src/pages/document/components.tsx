import { Link } from "react-router-dom"
import {
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  FileSpreadsheet,
  FileText,
  Mail,
  Network,
  Search,
} from "lucide-react"

import { downloadUrl } from "@/api/client"
import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { EmptyState } from "@/components/layout/EmptyState"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { formatBytes, formatDate, cn } from "@/lib/utils"
import type {
  DocumentEntity,
  DocumentGraph,
  DocumentPage,
  DocumentTimelineEvent,
} from "@/types/api"

import { entityLabel } from "./useDocumentDetail"

// ---------------------------------------------------------------------------
// HighlightedText — used by the OCR text card
// ---------------------------------------------------------------------------
function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

export function HighlightedText({ text, query }: { text: string; query: string }) {
  const trimmed = query.trim()
  if (!trimmed) return <>{text}</>
  const parts = text.split(new RegExp(`(${escapeRegExp(trimmed)})`, "gi"))
  return (
    <>
      {parts.map((part, index) =>
        part.toLowerCase() === trimmed.toLowerCase() ? (
          <mark key={index} className="rounded bg-amber-200 px-0.5">
            {part}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// EntityCard — used by the key entities card
// ---------------------------------------------------------------------------
export function EntityCard({ entity }: { entity: DocumentEntity }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-md border bg-[var(--bg-surface)] px-3 py-2.5">
      <span className="text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wide">
        {entityLabel(entity.entity_type)}
      </span>
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-semibold text-[var(--text-primary)]">
          {entity.entity_value}
        </span>
        {entity.confidence != null && (
          <ConfidenceBadge value={entity.confidence} showLabel={false} className="scale-75" />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// TimelineEventRow
// ---------------------------------------------------------------------------
export function TimelineEventRow({
  event,
  isLast,
}: {
  event: DocumentTimelineEvent
  isLast: boolean
}) {
  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <span className="mt-1.5 h-2.5 w-2.5 flex-shrink-0 rounded-full border-2 border-[var(--primary)] bg-[var(--bg-surface)]" />
        {!isLast && <span className="w-0.5 flex-1 bg-[var(--border)]" />}
      </div>
      <div className={cn("pb-3", isLast && "pb-0")}>
        <p className="text-[13px] font-medium text-[var(--text-primary)]">{event.title}</p>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-[var(--text-muted)]">
          <span>{formatDate(event.created_at)}</span>
          {event.actor_user_id && <span>· Usuario #{event.actor_user_id}</span>}
        </div>
        {event.description && (
          <p className="mt-0.5 text-[12px] text-[var(--text-secondary)]">{event.description}</p>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// DocumentGraphView
// ---------------------------------------------------------------------------
export function DocumentGraphView({ graph }: { graph: DocumentGraph }) {
  return (
    <div className="space-y-3 text-sm">
      <div className="flex gap-2">
        <Badge variant="neutral">{graph.nodes.length} documentos</Badge>
        <Badge variant="info">{graph.edges.length} relaciones</Badge>
      </div>
      {graph.edges.length > 0 && (
        <div className="max-h-[200px] overflow-auto rounded-md border">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-[var(--bg-surface-2)] text-left">
                <th className="px-2 py-1.5 font-medium">Relación</th>
                <th className="px-2 py-1.5 font-medium">Desde</th>
                <th className="px-2 py-1.5 font-medium">Hasta</th>
                <th className="px-2 py-1.5 font-medium">Detalle</th>
              </tr>
            </thead>
            <tbody>
              {graph.edges.map((edge, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-[var(--bg-surface-2)]">
                  <td className="px-2 py-1.5 font-medium capitalize">{edge.relation}</td>
                  <td className="px-2 py-1.5">
                    <Link
                      to={`/documents/${edge.from_document_id}`}
                      className="text-[var(--sky)] hover:underline"
                    >
                      #{edge.from_document_id}
                    </Link>
                  </td>
                  <td className="px-2 py-1.5">
                    <Link
                      to={`/documents/${edge.to_document_id}`}
                      className="text-[var(--sky)] hover:underline"
                    >
                      #{edge.to_document_id}
                    </Link>
                  </td>
                  <td className="px-2 py-1.5 text-[var(--text-muted)]">{edge.label ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex flex-wrap gap-1.5">
        {graph.nodes.map((node) => (
          <Link
            key={node.document_id}
            to={`/documents/${node.document_id}`}
            className={cn(
              "rounded-md border px-2 py-1 text-xs transition-colors hover:bg-[var(--bg-surface-2)]",
              node.document_id === graph.nodes[0].document_id &&
                "border-[var(--primary)] bg-[var(--primary-light)]",
            )}
          >
            <span className="font-medium">{node.filename}</span>
            <span className="ml-1.5 text-[var(--text-muted)]">{node.document_type}</span>
          </Link>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// UnsupportedPreviewCard — fallback for file types without a thumbnail
// ---------------------------------------------------------------------------
function previewKind(
  extension: string | null | undefined,
): "page" | "image" | "excel" | "email" | "other" {
  const ext = (extension ?? "").toLowerCase()
  if (ext === ".pdf") return "page"
  if ([".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"].includes(ext)) return "image"
  if ([".xlsx", ".xls", ".xlsm"].includes(ext)) return "excel"
  if (ext === ".msg") return "email"
  return "other"
}

function typeLabel(extension: string | null | undefined): string {
  const ext = (extension ?? "").toLowerCase()
  if (ext === ".pdf") return "Documento PDF"
  if (ext === ".docx") return "Documento Word (.docx)"
  if (ext === ".doc") return "Documento Word (.doc)"
  if ([".xlsx", ".xls", ".xlsm"].includes(ext)) return "Hoja de cálculo"
  if (ext === ".msg") return "Email Outlook"
  if (ext === ".eml") return "Email"
  if ([".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"].includes(ext)) return "Imagen"
  if ([".txt", ".csv", ".tsv", ".log"].includes(ext)) return "Texto plano"
  if (ext === ".dwg") return "Plano CAD"
  if (ext === ".lnk") return "Acceso directo"
  return ext ? `Archivo ${ext}` : "Archivo"
}

export function UnsupportedPreviewCard({
  document,
}: {
  document: {
    id: number
    original_filename: string
    extension: string | null
    file_size: number
    file_hash: string
    mime_type?: string | null
  }
}) {
  const kind = previewKind(document.extension)
  const Icon = kind === "excel" ? FileSpreadsheet : kind === "email" ? Mail : kind === "page" ? FileText : FileText
  const ext = (document.extension ?? "").toLowerCase()

  const tips: Record<string, string> = {
    ".pdf": "El PDF fue procesado por OCR. Las páginas se extraen como imágenes durante el procesamiento. Si no hay imagen, el procesamiento puede no haber terminado.",
    ".docx": "El documento Word fue procesado por OCR. El texto extraído está en la pestaña OCR.",
    ".doc": "El documento Word (.doc) fue procesado. El texto extraído está en la pestaña OCR.",
    ".msg": "El email Outlook fue procesado. El contenido (asunto, remitente, cuerpo) está en las entidades y el texto OCR.",
    ".eml": "El email fue procesado. El contenido está en las entidades y el texto OCR.",
    ".dwg": "El plano CAD fue procesado. Las medidas y entidades están en la pestaña Entidades.",
    ".txt": "El texto plano fue procesado. Todo el contenido está en la pestaña OCR.",
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 bg-[var(--bg-surface-2)] px-6 py-10">
      <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-[var(--bg-surface-3)] text-[var(--text-muted)]">
        <Icon className="h-7 w-7" />
      </div>
      <div className="text-center">
        <p className="text-[14px] font-semibold text-[var(--text-primary)]">
          {typeLabel(document.extension)}
        </p>
        <p className="mt-1 max-w-sm text-[12px] leading-relaxed text-[var(--text-muted)]">
          {tips[ext] ?? "No hay vista previa visual. El contenido fue procesado por OCR — revisa la pestaña OCR para ver el texto extraído."}
        </p>
      </div>
      <dl className="grid w-full max-w-sm grid-cols-2 gap-x-4 gap-y-1.5 rounded-lg border bg-[var(--bg-surface)] px-4 py-3 text-[12px]">
        <dt className="text-[var(--text-muted)]">Tipo</dt>
        <dd className="text-right font-mono text-[11px]">{document.extension ?? "—"}</dd>
        <dt className="text-[var(--text-muted)]">Tamaño</dt>
        <dd className="text-right">{formatBytes(document.file_size)}</dd>
        {document.mime_type && (
          <>
            <dt className="text-[var(--text-muted)]">MIME</dt>
            <dd className="truncate text-right font-mono text-[11px]" title={document.mime_type}>{document.mime_type}</dd>
          </>
        )}
        <dt className="text-[var(--text-muted)]">SHA256</dt>
        <dd className="truncate text-right font-mono text-[11px]" title={document.file_hash}>{document.file_hash.slice(0, 16)}…</dd>
      </dl>
      <Button asChild size="sm" variant="default" className="rounded-lg">
        <a href={downloadUrl(document.id)}><Download className="mr-1 h-3.5 w-3.5" /> Descargar</a>
      </Button>
    </div>
  )
}

// Re-export the search input as a reusable piece.
export function OcrSearchInput({
  value,
  onChange,
}: {
  value: string
  onChange: (v: string) => void
}) {
  return (
    <div className="relative w-full max-w-[200px]">
      <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--text-muted)]" />
      <Input
        className="h-8 pl-7 text-xs"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Buscar en documento..."
      />
    </div>
  )
}

// CollapsibleCard — a Card with a clickable header that toggles a body
export function CollapsibleCard({
  title,
  icon,
  open,
  onToggle,
  children,
  rightSlot,
}: {
  title: string
  icon?: React.ReactNode
  open: boolean
  onToggle: () => void
  children: React.ReactNode
  rightSlot?: React.ReactNode
}) {
  return (
    <Card>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-[var(--bg-surface-2)]/80"
      >
        <CardTitle className="flex items-center gap-2 text-[14px] font-semibold">
          {icon}
          {title}
        </CardTitle>
        <div className="flex items-center gap-2">
          {rightSlot}
          {open ? (
            <ChevronDown className="h-4 w-4 text-[var(--text-muted)]" />
          ) : (
            <ChevronRight className="h-4 w-4 text-[var(--text-muted)]" />
          )}
        </div>
      </button>
      {open && <CardContent className="border-t p-3">{children}</CardContent>}
    </Card>
  )
}

// Helper for the blocks table (used by the CollapsibleCard body)
export function BlocksTable({
  blocks,
}: {
  blocks: Array<{
    id: number
    page_number: number | null
    block_type: string
    text: string | null
    confidence: number | null
  }>
}) {
  if (!blocks.length) {
    return (
      <EmptyState
        title="Sin bloques"
        description="Este documento no tiene bloques OCR indexados."
      />
    )
  }
  return (
    <div className="max-h-[200px] overflow-auto p-0">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-[var(--bg-surface-2)] text-left text-[11px] uppercase text-[var(--text-muted)]">
            <th className="px-3 py-2 font-medium">Pág.</th>
            <th className="px-3 py-2 font-medium">Tipo</th>
            <th className="px-3 py-2 font-medium">Texto</th>
            <th className="px-3 py-2 font-medium text-right">Conf.</th>
          </tr>
        </thead>
        <tbody>
          {blocks.slice(0, 30).map((b) => (
            <tr
              key={b.id}
              data-block-id={b.id}
              className="border-b last:border-0 hover:bg-[var(--bg-surface-2)] transition-colors"
            >
              <td className="px-3 py-1.5 text-xs">{b.page_number ?? "—"}</td>
              <td className="px-3 py-1.5 text-xs capitalize">{b.block_type}</td>
              <td className="max-w-[240px] truncate px-3 py-1.5 text-xs">{b.text ?? "—"}</td>
              <td className="px-3 py-1.5 text-right text-xs text-[var(--text-muted)]">
                {b.confidence != null ? `${Math.round(b.confidence * 100)}%` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Helper for the "other entities" table
export function OtherEntitiesTable({ entities }: { entities: DocumentEntity[] }) {
  if (!entities.length) return null
  return (
    <div className="max-h-[200px] overflow-auto p-0">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b bg-[var(--bg-surface-2)] text-left text-[11px] uppercase text-[var(--text-muted)]">
            <th className="px-3 py-2 font-medium">Tipo</th>
            <th className="px-3 py-2 font-medium">Valor</th>
            <th className="px-3 py-2 font-medium text-right">Conf.</th>
          </tr>
        </thead>
        <tbody>
          {entities.slice(0, 30).map((e) => (
            <tr key={e.id} className="border-b last:border-0 hover:bg-[var(--bg-surface-2)]">
              <td className="px-3 py-1.5 text-xs capitalize">{e.entity_type.replace(/_/g, " ")}</td>
              <td className="max-w-[300px] truncate px-3 py-1.5 text-xs">{e.entity_value}</td>
              <td className="px-3 py-1.5 text-right text-xs text-[var(--text-muted)]">
                {e.confidence != null ? `${Math.round(e.confidence * 100)}%` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Re-export the page-level CardHeader for the "Visor" / "Texto OCR" titles.
export function VisorCardHeader({ children }: { children: React.ReactNode }) {
  return (
    <CardHeader className="flex-row items-center justify-between border-b bg-[var(--bg-surface-2)]/80 py-3">
      <CardTitle className="text-[14px] font-semibold">{children}</CardTitle>
    </CardHeader>
  )
}

// Re-export the Copy icon usage for the OCR card "copy page" affordance.
export function CopyButton({ text, title }: { text: string; title: string }) {
  return (
    <button
      type="button"
      title={title}
      onClick={() => navigator.clipboard?.writeText(text).catch(() => {})}
      className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
    >
      <Copy className="h-3 w-3" />
    </button>
  )
}

// Network icon re-export so the page doesn't need to import from lucide
// just for one collapsible card header.
export { Network }
