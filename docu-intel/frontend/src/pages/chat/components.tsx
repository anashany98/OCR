import { Link } from "react-router-dom"
import {
  ArrowRight,
  Bot,
  ExternalLink,
  FileText,
  ImageIcon,
  Link2,
  Map as MapIcon,
  MessageCircle,
  Receipt,
  Sparkles,
} from "lucide-react"

import { pageImageUrl, thumbnailUrl } from "@/api/core"
import { Badge } from "@/components/ui/badge"
import { EmptyChatIllustration } from "@/components/illustrations/EditorialIllustrations"
import { formatDate, formatMoney, cn } from "@/lib/utils"
import type { AIAnswer, AIQuestion, ResolvedDocument, ResolvedDocumentEntity } from "@/types/api"

import type { ChatMessage } from "./useChat"

// ---------------------------------------------------------------------------
// Suggested prompts shown on the empty-state welcome card.
// ---------------------------------------------------------------------------
export const SUGGESTED_PROMPTS = [
  "¿Qué presupuestos superan los 10.000 € este mes?",
  "Resumen de los pedidos del proveedor García",
  "¿Hay planos sin escala válida pendientes de revisar?",
  "¿Cuántos documentos con baja confianza OCR hay ahora mismo?",
]

// ---------------------------------------------------------------------------
// Tiny bouncing dot, reused by both typing indicators.
// ---------------------------------------------------------------------------
export function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="block h-1.5 w-1.5 rounded-full bg-[var(--text-muted)]"
      style={{
        animation: "chat-bounce 1.1s infinite ease-in-out",
        animationDelay: delay,
      }}
    />
  )
}

export function TypingIndicator() {
  return (
    <div className="flex items-start gap-3">
      <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-[var(--accent-light)] text-[var(--accent)]">
        <Bot className="h-4 w-4" />
      </div>
      <div className="rounded-2xl rounded-tl-sm border border-[var(--border)] bg-[var(--bg-surface-2)]/60 px-4 py-3">
        <div className="flex items-center gap-1.5">
          <Dot delay="0ms" />
          <Dot delay="120ms" />
          <Dot delay="240ms" />
        </div>
      </div>
    </div>
  )
}

export function TypingIndicatorInline() {
  return (
    <div className="flex items-center gap-1.5 py-0.5">
      <Dot delay="0ms" />
      <Dot delay="120ms" />
      <Dot delay="240ms" />
      <span className="ml-1 text-[12px] text-[var(--text-muted)]">pensando…</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Welcome card with suggested prompts.
// ---------------------------------------------------------------------------
export function WelcomeCard({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="flex flex-col items-center gap-5 rounded-2xl border border-dashed border-[var(--border-2)] bg-[var(--bg-surface-2)]/30 px-6 py-8 text-center">
      <div className="flex h-32 w-40 items-center justify-center text-[var(--accent)]">
        <EmptyChatIllustration />
      </div>
      <div className="space-y-1.5">
        <h2 className="font-display text-[22px] font-medium tracking-tight text-[var(--text-primary)]">
          Hola, soy tu asistente documental
        </h2>
        <p className="mx-auto max-w-lg text-[13px] text-[var(--text-muted)]">
          Preguntame lo que quieras sobre los documentos del proyecto. Te respondo en lenguaje
          natural, entiendo PDFs, emails, planos e imagenes, y cito siempre la fuente para que
          puedas comprobarlo.
        </p>
      </div>
      <div className="grid w-full max-w-2xl gap-2 sm:grid-cols-2">
        {SUGGESTED_PROMPTS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => onPick(p)}
            className="group flex items-start gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2.5 text-left text-[13px] text-[var(--text-secondary)] transition-colors hover:border-[var(--accent)] hover:bg-[var(--bg-surface)] hover:text-[var(--text-primary)]"
          >
            <MessageCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-[var(--text-muted)] group-hover:text-[var(--accent)]" />
            <span className="leading-snug">{p}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// History sidebar row.
// ---------------------------------------------------------------------------
export function HistoryRow({ item, onPick }: { item: AIQuestion; onPick: (q: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onPick(item.question)}
      className="flex w-full flex-col gap-0.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-[var(--bg-surface-2)]"
    >
      <span className="line-clamp-2 text-[13px] text-[var(--text-primary)]">{item.question}</span>
      <span className="text-[11px] text-[var(--text-muted)]">{formatDate(item.created_at)}</span>
    </button>
  )
}

// ---------------------------------------------------------------------------
// Action button used inside the assistant message bubble.
// ---------------------------------------------------------------------------
export function ActionButton({
  onClick,
  title,
  ariaLabel,
  children,
  hoverColor = "primary",
}: {
  onClick: () => void
  title: string
  ariaLabel: string
  children: React.ReactNode
  hoverColor?: "primary" | "warning"
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={ariaLabel}
      className={cn(
        "inline-flex h-6 w-6 items-center justify-center rounded transition-colors",
        "hover:bg-[var(--bg-surface-2)]",
        hoverColor === "warning"
          ? "hover:text-[var(--warning)]"
          : "hover:text-[var(--text-primary)]",
      )}
    >
      {children}
    </button>
  )
}

// ---------------------------------------------------------------------------
// Follow-up suggestion chips.
// ---------------------------------------------------------------------------
export function FollowupChips({
  followups,
  onPick,
}: {
  followups: string[]
  onPick: (q: string) => void
}) {
  if (!followups || followups.length === 0) return null
  return (
    <div className="mt-2 flex max-w-[88%] flex-wrap gap-1.5 sm:max-w-[80%]">
      {followups.map((q) => (
        <button
          key={q}
          type="button"
          onClick={() => onPick(q)}
          className="group inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--bg-surface)] px-2.5 py-1 text-[11.5px] text-[var(--text-secondary)] transition-colors hover:border-[var(--accent)] hover:bg-[var(--accent-faint)] hover:text-[var(--accent)]"
        >
          <Sparkles className="h-3 w-3 text-[var(--text-muted)] group-hover:text-[var(--accent)]" />
          <span className="line-clamp-1">{q}</span>
          <ArrowRight className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Source chip.
// ---------------------------------------------------------------------------
export function SourceChip({ source }: { source: NonNullable<AIAnswer["sources"]>[number] }) {
  if (!source.document_id) {
    return (
      <span className="inline-flex max-w-[260px] items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-0.5 text-[11px] text-[var(--text-muted)]">
        Doc #{source.document_id ?? "—"}
        {source.page_number != null && ` · pág. ${source.page_number}`}
      </span>
    )
  }
  const pageHash = source.page_number != null ? `#page=${source.page_number}` : ""
  const blockHash = source.block_id != null ? `&block=${source.block_id}` : ""
  return (
    <Link
      to={`/documents/${source.document_id}${pageHash}${blockHash}`}
      className="inline-flex max-w-[260px] items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-0.5 text-[11px] text-[var(--text-secondary)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
      title={source.excerpt ?? ""}
    >
      <ExternalLink className="h-3 w-3 flex-shrink-0" />
      <span className="truncate">Doc #{source.document_id}</span>
      {source.page_number != null && <span>· pág. {source.page_number}</span>}
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Document preview card (used by ResolvedDocumentCard).
// ---------------------------------------------------------------------------
export function DocumentPreview({
  documentId,
  filename,
}: {
  documentId: number
  filename: string
}) {
  const ext = (filename.split(".").pop() || "").toLowerCase()
  const isImage = ["png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"].includes(ext)
  const thumb = thumbnailUrl(documentId)
  const firstPage = pageImageUrl(documentId, 1)
  const previewSrc = isImage ? thumb : firstPage
  return (
    <div className="mt-2 flex items-stretch gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)]/50 p-2">
      <a
        href={`/documents/${documentId}`}
        className="block flex-shrink-0 overflow-hidden rounded-md border border-[var(--border)] bg-[var(--bg-surface)]"
        title="Abrir documento"
        target="_blank"
        rel="noreferrer"
      >
        {/* The image is a visual preview of a chat-cited document; the surrounding link's ``title`` attribute and the citation text already carry the accessible name. ``alt=""`` marks the image as decorative so screen readers skip it. */}
        <img
          alt=""
          src={previewSrc}
          loading="lazy"
          className="block h-20 w-16 object-cover"
          onError={(e) => {
            ;(e.currentTarget as HTMLImageElement).style.display = "none"
          }}
        />
      </a>
      <div className="flex min-w-0 flex-1 flex-col justify-center text-[11.5px] leading-snug text-[var(--text-muted)]">
        <span className="mb-0.5 inline-flex items-center gap-1 font-medium uppercase tracking-wide text-[var(--text-secondary)]">
          {isImage ? <ImageIcon className="h-3 w-3" /> : <FileText className="h-3 w-3" />}
          Vista previa · {ext.toUpperCase()}
        </span>
        <a
          href={`/documents/${documentId}`}
          className="truncate font-mono text-[11px] text-[var(--text-secondary)] hover:text-[var(--accent)]"
          title={filename}
        >
          {filename}
        </a>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Entity row (used by ResolvedDocumentCard).
// ---------------------------------------------------------------------------
export function EntityRow({
  icon,
  label,
  e,
}: {
  icon: React.ReactNode
  label: string
  e: ResolvedDocumentEntity
}) {
  const facts: Array<{ k: string; v: string }> = []
  if (e.number) facts.push({ k: "Nº", v: String(e.number) })
  if (e.client) facts.push({ k: "Cliente", v: String(e.client) })
  if (e.supplier) facts.push({ k: "Proveedor", v: String(e.supplier) })
  if (e.total_amount != null)
    facts.push({ k: "Importe", v: formatMoney(e.total_amount, { currency: e.currency || "EUR" }) })
  if (e.date) facts.push({ k: "Fecha", v: String(e.date) })
  if (e.status) facts.push({ k: "Estado", v: String(e.status) })
  if (e.accepted === true) facts.push({ k: "", v: "aceptado" })
  if (e.accepted === false) facts.push({ k: "", v: "no aceptado" })
  if (e.project_name) facts.push({ k: "Proyecto", v: String(e.project_name) })
  if (e.scale_text)
    facts.push({
      k: "Escala",
      v: `${e.scale_text}${e.has_valid_scale === false ? " (no válida)" : ""}`,
    })
  if (e.related_budget_id)
    facts.push({ k: "", v: `vinculado a presupuesto #${e.related_budget_id}` })
  if (e.related_order_id) facts.push({ k: "", v: `vinculado a pedido #${e.related_order_id}` })
  if (typeof e.line_count === "number" && e.line_count > 0)
    facts.push({ k: "Líneas", v: String(e.line_count) })
  if (!facts.length) return null
  return (
    <div className="mt-1.5 flex items-start gap-1.5">
      <span className="mt-0.5 text-[var(--text-muted)]">{icon}</span>
      <div className="min-w-0 flex-1">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
          {label}
        </span>
        <p className="text-[12.5px] leading-snug text-[var(--text-primary)]">
          {facts.map((f, i) => (
            <span key={i}>
              {f.k && <span className="text-[var(--text-muted)]">{f.k}: </span>}
              <span>{f.v}</span>
              {i < facts.length - 1 ? " · " : ""}
            </span>
          ))}
        </p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Resolved document card (above the assistant's prose when the user mentioned
// a specific file).
// ---------------------------------------------------------------------------
export function ResolvedDocumentCard({ resolved }: { resolved: ResolvedDocument }) {
  const doc = resolved.document
  const entities = doc.entities || {}
  const related = resolved.related || []

  // Detect critical missing fields so the user can fix them from the
  // document page.
  const missing: string[] = []
  if (entities.budget) {
    if (!entities.budget.client) missing.push("cliente del presupuesto")
    if (entities.budget.total_amount == null) missing.push("importe del presupuesto")
  }
  if (entities.order && !entities.order.supplier) missing.push("proveedor del pedido")
  if (entities.invoice && entities.invoice.total_amount == null)
    missing.push("importe de la factura")

  return (
    <div className="mb-3 space-y-2 rounded-xl border border-[var(--accent)]/30 bg-[var(--accent-faint)]/60 p-3 text-[12.5px]">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--accent)]">
            <FileText className="h-3.5 w-3.5" />
            Documento que he analizado
          </div>
          <Link
            to={`/documents/${doc.id}`}
            className="mt-0.5 block truncate text-[13px] font-semibold text-[var(--text-primary)] hover:text-[var(--accent)]"
            title={doc.filename}
          >
            {doc.filename}
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
            {doc.document_type && (
              <Badge variant="neutral" className="capitalize">
                {doc.document_type}
              </Badge>
            )}
            <Badge
              variant={
                doc.status === "processed" || doc.status === "processed_ok" ? "success" : "warning"
              }
            >
              {doc.status}
            </Badge>
            {doc.confidence != null && <span>OCR {Math.round(doc.confidence * 100)}%</span>}
            {doc.page_count != null && <span>· {doc.page_count} pág.</span>}
            {missing.length > 0 && (
              <Link
                to={`/documents/${doc.id}`}
                className="inline-flex items-center gap-1 rounded border border-[var(--warning)] bg-[var(--warning-faint)] px-1.5 py-0.5 text-[10.5px] font-medium text-[var(--warning)] hover:bg-[var(--warning-light)]"
                title={`Faltan: ${missing.join(", ")}. Pulsa para abrir el documento y completar los datos.`}
              >
                Datos incompletos ({missing.length})
              </Link>
            )}
          </div>
        </div>
      </div>

      {entities.budget && (
        <EntityRow
          icon={<FileText className="h-3.5 w-3.5" />}
          label="Presupuesto"
          e={entities.budget}
        />
      )}
      {entities.order && (
        <EntityRow icon={<Receipt className="h-3.5 w-3.5" />} label="Pedido" e={entities.order} />
      )}
      {entities.invoice && (
        <EntityRow
          icon={<Receipt className="h-3.5 w-3.5" />}
          label="Factura"
          e={entities.invoice}
        />
      )}
      {entities.plan && (
        <EntityRow icon={<MapIcon className="h-3.5 w-3.5" />} label="Plano" e={entities.plan} />
      )}

      {doc.vision?.description && (
        <div className="mt-2 rounded-lg border border-[var(--info)]/30 bg-[var(--info-faint)]/60 p-2.5">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--info)]">
            <Sparkles className="h-3.5 w-3.5" />
            Vision aplicada · {doc.vision.model}
          </div>
          <p className="whitespace-pre-wrap text-[12.5px] leading-snug text-[var(--text-primary)]">
            {doc.vision.description}
          </p>
        </div>
      )}

      {related.length > 0 && (
        <div className="mt-1.5 border-t border-[var(--accent)]/20 pt-2">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--accent)]">
            <Link2 className="h-3.5 w-3.5" />
            Documentos relacionados ({related.length})
          </div>
          <ul className="space-y-1">
            {related.slice(0, 6).map((r) => (
              <li key={r.document_id} className="flex items-start gap-1.5 text-[12px]">
                <span className="mt-0.5 text-[var(--accent)]">↳</span>
                <div className="min-w-0 flex-1">
                  <Link
                    to={`/documents/${r.document_id}`}
                    className="font-medium text-[var(--text-primary)] hover:text-[var(--accent)]"
                  >
                    {r.filename}
                  </Link>
                  <p className="text-[11px] text-[var(--text-muted)]">{r.label}</p>
                </div>
              </li>
            ))}
            {related.length > 6 && (
              <li className="text-[11px] text-[var(--text-muted)]">+{related.length - 6} más</li>
            )}
          </ul>
        </div>
      )}
    </div>
  )
}

// Re-export the chat message type so other chat components can
// consume it without depending on the hook file.
export type { ChatMessage }
