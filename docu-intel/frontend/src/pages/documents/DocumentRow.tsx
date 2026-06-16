/**
 * F8: extracted row component for the operations documents table.
 *
 * Pulled out of ``DocumentsPage.tsx`` so the page itself focuses on
 * orchestration (state + queries + filters) and the row rendering
 * lives in a focused, testable file. The component is intentionally
 * pure: it receives the document, the selected flag and the two
 * callbacks the parent owns. The parent owns the selection state
 * and the reprocess mutation so the row stays decoupled from the
 * TanStack Query client and the upload state.
 */
import { Link } from "react-router-dom"
import { Download, Eye, FileSpreadsheet, RefreshCcw } from "lucide-react"

import { downloadUrl } from "@/api/client"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Button } from "@/components/ui/button"
import { TableCell, TableRow } from "@/components/ui/table"
import { formatBytes, formatDate } from "@/lib/utils"
import type { Document } from "@/types/api"

type DocumentRowProps = {
  document: Document
  selected: boolean
  onToggle: () => void
  onReprocess: () => void
}

export function DocumentRow({ document, selected, onToggle, onReprocess }: DocumentRowProps) {
  return (
    <TableRow className={selected ? "bg-cyan-50/60" : undefined}>
      <TableCell>
        <input
          type="checkbox"
          aria-label={`Seleccionar ${document.original_filename}`}
          checked={selected}
          onChange={onToggle}
        />
      </TableCell>
      <TableCell className="min-w-[260px]">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="h-4 w-4 text-muted-foreground" />
          <div className="min-w-0">
            <p className="truncate font-medium">{document.original_filename}</p>
            <p className="truncate text-xs text-muted-foreground">
              {document.source_path ?? document.file_hash}
            </p>
          </div>
        </div>
      </TableCell>
      <TableCell>{document.document_type}</TableCell>
      <TableCell>
        <StatusBadge status={document.status} />
      </TableCell>
      <TableCell>
        <StatusBadge status={document.quality_status ?? "-"} />
      </TableCell>
      <TableCell>
        {document.confidence != null ? `${Math.round(document.confidence * 100)}%` : "-"}
      </TableCell>
      <TableCell>{formatBytes(document.file_size)}</TableCell>
      <TableCell>{formatDate(document.created_at)}</TableCell>
      <TableCell>
        <div className="flex justify-end gap-1">
          <Button asChild variant="ghost" size="icon" title="Ver documento" aria-label={`Ver ${document.original_filename}`}>
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
