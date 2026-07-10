/**
 * F8: extracted row component for the operations documents table.
 *
 * F8b: state and quality badges are stacked in one cell (column 3)
 * to reduce the table from 9 columns to 7, with size+date merged
 * into a single cell. Selection, navigation, reprocess and download
 * stay as inline icon buttons to keep the row scannable.
 */
import { useCallback } from "react"
import { Link } from "react-router-dom"
import { useQueryClient } from "@tanstack/react-query"
import { Download, Eye, FileSpreadsheet, RefreshCcw } from "lucide-react"

import { api, downloadUrl } from "@/api/client"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Button } from "@/components/ui/button"
import { TableCell, TableRow } from "@/components/ui/table"
import { cn, formatBytes, formatDate } from "@/lib/utils"
import type { Document } from "@/types/api"

type DocumentRowProps = {
  document: Document
  selected: boolean
  onToggle: () => void
  onReprocess: () => void
}

export function DocumentRow({ document, selected, onToggle, onReprocess }: DocumentRowProps) {
  const queryClient = useQueryClient()
  const confidencePct = document.confidence != null ? Math.round(document.confidence * 100) : null

  // Prefetch document detail on hover so navigation feels instant.
  const prefetchDocument = useCallback(() => {
    queryClient.prefetchQuery({
      queryKey: ["document", document.id],
      queryFn: () => api.document(document.id),
      staleTime: 60_000,
    })
  }, [queryClient, document.id])
  const confidenceTone =
    confidencePct == null
      ? "bg-muted-foreground/30"
      : confidencePct < 50
        ? "bg-red-500"
        : confidencePct < 70
          ? "bg-amber-500"
          : "bg-emerald-500"

  return (
    <TableRow className={cn(selected && "bg-cyan-50/60 hover:bg-cyan-50/80")}>
      <TableCell className="py-3">
        <input
          type="checkbox"
          aria-label={`Seleccionar ${document.original_filename}`}
          checked={selected}
          onChange={onToggle}
        />
      </TableCell>
      <TableCell className="min-w-[280px] py-3">
        <div className="flex items-center gap-2.5">
          <FileSpreadsheet className="h-4 w-4 shrink-0 text-[var(--text-muted)]" />
          <div className="min-w-0">
            <Link
              to={`/documents/${document.id}`}
              className="block truncate text-sm font-medium text-foreground hover:underline"
              title={document.original_filename}
              onMouseEnter={prefetchDocument}
            >
              {document.original_filename}
            </Link>
            <p
              className="truncate text-[11px] text-[var(--text-muted)]"
              title={document.source_path ?? undefined}
            >
              {document.source_path ?? document.file_hash?.slice(0, 16)}
            </p>
          </div>
        </div>
      </TableCell>
      <TableCell className="py-3">
        <div className="flex flex-col gap-1.5">
          <StatusBadge status={document.status} />
          <StatusBadge status={document.quality_status ?? "-"} />
        </div>
      </TableCell>
      <TableCell className="py-3 text-xs text-[var(--text-muted)]">{document.document_type}</TableCell>
      <TableCell className="py-3 text-right tabular-nums">
        <span className="inline-flex items-center gap-1.5">
          <span className={cn("h-1.5 w-1.5 rounded-full", confidenceTone)} aria-hidden="true" />
          <span className="text-sm">{confidencePct == null ? "—" : `${confidencePct}%`}</span>
        </span>
      </TableCell>
      <TableCell className="py-3 text-xs tabular-nums text-[var(--text-muted)]">
        <div className="flex flex-col gap-0.5">
          <span className="font-medium text-foreground">{formatBytes(document.file_size)}</span>
          <span>{formatDate(document.created_at)}</span>
        </div>
      </TableCell>
      <TableCell className="py-3">
        <div className="flex justify-end gap-1">
          <Button
            asChild
            variant="ghost"
            size="icon"
            title="Ver documento"
            aria-label={`Ver ${document.original_filename}`}
          >
            <Link to={`/documents/${document.id}`}>
              <Eye aria-hidden="true" />
            </Link>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            title="Reprocesar"
            aria-label={`Reprocesar ${document.original_filename}`}
            onClick={onReprocess}
          >
            <RefreshCcw aria-hidden="true" />
          </Button>
          <Button
            asChild
            variant="ghost"
            size="icon"
            title="Descargar"
            aria-label={`Descargar ${document.original_filename}`}
          >
            <a href={downloadUrl(document.id)}>
              <Download aria-hidden="true" />
            </a>
          </Button>
        </div>
      </TableCell>
    </TableRow>
  )
}
