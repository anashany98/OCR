import { useState } from "react"
import { FileText, ImageIcon, ExternalLink } from "lucide-react"

import { thumbnailUrl } from "@/api/core"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

interface SourceCardProps {
  documentId: number
  filename: string
  documentType?: string
  pageNumber?: number
  confidence?: number
  excerpt?: string
  className?: string
}

const TYPE_COLORS: Record<string, string> = {
  presupuesto: "bg-[var(--info-light)] text-[var(--text-on-info)]",
  pedido: "bg-[var(--success-light)] text-[var(--text-on-success)]",
  factura: "bg-[var(--warning-light)] text-[var(--text-on-warning)]",
  plano: "bg-[var(--accent-light)] text-[var(--accent)]",
  imagen: "bg-[var(--bg-surface-2)] text-[var(--text-muted)]",
  excel: "bg-[var(--bg-surface-2)] text-[var(--text-muted)]",
}

export function SourceCard({
  documentId,
  filename,
  documentType,
  pageNumber,
  confidence,
  excerpt,
  className,
}: SourceCardProps) {
  const [imgError, setImgError] = useState(false)
  const typeClass = documentType ? TYPE_COLORS[documentType] ?? "bg-[var(--bg-surface-2)] text-[var(--text-muted)]" : ""

  return (
    <a
      href={`/documents/${documentId}${pageNumber ? `#page=${pageNumber}` : ""}`}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        "group flex gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-2.5 transition-all hover:border-[var(--accent)]/30 hover:shadow-sm",
        className,
      )}
    >
      {/* Thumbnail */}
      <div className="flex h-12 w-16 flex-shrink-0 items-center justify-center overflow-hidden rounded-md bg-[var(--bg-surface-2)]">
        {!imgError ? (
          <img
            src={thumbnailUrl(documentId)}
            alt=""
            className="h-full w-full object-cover"
            onError={() => setImgError(true)}
          />
        ) : (
          <FileText className="h-5 w-5 text-[var(--text-muted)]" />
        )}
      </div>

      {/* Info */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <p className="truncate text-[11px] font-medium text-[var(--text-primary)] group-hover:text-[var(--accent)]">
            {filename}
          </p>
          <ExternalLink className="h-2.5 w-2.5 flex-shrink-0 text-[var(--text-muted)] opacity-0 group-hover:opacity-100" />
        </div>

        <div className="mt-0.5 flex flex-wrap items-center gap-1">
          {documentType && (
            <span className={cn("rounded px-1.5 py-0.5 text-[9px] font-semibold", typeClass)}>
              {documentType}
            </span>
          )}
          {pageNumber && (
            <span className="text-[9px] text-[var(--text-muted)]">Pág. {pageNumber}</span>
          )}
          {confidence != null && (
            <span className={cn(
              "text-[9px] font-medium",
              confidence >= 0.85 ? "text-[var(--success)]" : confidence >= 0.7 ? "text-[var(--warning)]" : "text-[var(--danger)]",
            )}>
              {Math.round(confidence * 100)}%
            </span>
          )}
        </div>

        {excerpt && (
          <p className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-[var(--text-muted)]">
            {excerpt}
          </p>
        )}
      </div>
    </a>
  )
}
