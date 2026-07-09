import { Link } from "react-router-dom"
import { toast } from "sonner"
import { Download, FileWarning, MapPin, RefreshCcw, RotateCcw, Save } from "lucide-react"

import { downloadUrl } from "@/api/client"
import { PermissionGate } from "@/components/layout/PermissionGate"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import { useDocumentDetail } from "./useDocumentDetail"

/**
 * F8 - Document detail page action toolbar.
 *
 * Extracted from ``DocumentDetailPage`` so the page shell stays
 * focused on layout. Renders the plan-annotation, reprocess,
 * correct-type, send-to-review and download buttons gated by the
 * user's role via :class:`PermissionGate`.
 *
 * The two "feature pending" buttons (Corregir tipo, Enviar a
 * revisión) call :func:`toast.info` instead of ``window.alert`` so
 * the message is announced through the standard accessible toast
 * channel (F9).
 */
export function DocumentActionToolbar({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const id = d.document?.id
  return (
    <div className="flex flex-wrap gap-1.5">
      {d.document?.document_type === "plano" && id ? (
        <PermissionGate roles={["admin", "gestor"]}>
          <Button asChild variant="outline" size="sm" className="h-8 text-xs">
            <Link to={`/documents/${id}/annotate-plan`}>
              <MapPin className="mr-1 h-3.5 w-3.5" />
              Anotar plano
            </Link>
          </Button>
        </PermissionGate>
      ) : null}
      <PermissionGate roles={["admin"]}>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          disabled={d.reprocess.isPending}
          onClick={() => d.reprocess.mutate()}
        >
          <RefreshCcw className="mr-1 h-3.5 w-3.5" />
          Reprocesar
        </Button>
      </PermissionGate>
      <PermissionGate roles={["admin", "gestor"]}>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          onClick={() => toast.info("Funcionalidad pendiente de implementar")}
        >
          <RotateCcw className="mr-1 h-3.5 w-3.5" />
          Corregir tipo
        </Button>
      </PermissionGate>
      <PermissionGate roles={["admin", "gestor"]}>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          onClick={() => toast.info("Funcionalidad pendiente de implementar")}
        >
          <FileWarning className="mr-1 h-3.5 w-3.5" />
          Enviar a revisión
        </Button>
      </PermissionGate>
      {id ? (
        <Button asChild size="sm" className="h-8 text-xs">
          <a href={downloadUrl(id)}>
            <Download className="mr-1 h-3.5 w-3.5" />
            Descargar
          </a>
        </Button>
      ) : null}
    </div>
  )
}

/**
 * F8 - Document OCR revision editor.
 *
 * Inline editor that lets the user correct the OCR text of the
 * currently-selected page. Saves a new revision via
 * ``d.saveRevision``; the button is disabled while the mutation
 * is in flight, while the edited text is empty, or while it is
 * identical to the original OCR text (so an empty save does not
 * pollute the revision log).
 */
export function DocumentOcrRevisionEditor({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const page = d.selectedPage
  if (!page) return null
  return (
    <section className="mt-4 rounded-md border bg-[var(--bg-surface-2)] p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <h4 className="text-[13px] font-semibold">Corrección OCR</h4>
          <p className="text-[11px] text-[var(--text-muted)]">
            Página {page.page_number} · {d.revisionsQ.data?.length ?? 0} revisiones
          </p>
        </div>
        <Button
          size="sm"
          className="h-7 text-xs"
          disabled={
            d.saveRevision.isPending || !d.editedText.trim() || d.editedText === (page.text ?? "")
          }
          onClick={() => d.saveRevision.mutate()}
        >
          <Save className="mr-1 h-3 w-3" />
          Guardar
        </Button>
      </div>
      <textarea
        className="min-h-[100px] w-full rounded-md border bg-[var(--bg-surface)] p-2.5 font-mono text-[12px] leading-6 outline-none focus:ring-2 focus:ring-[var(--primary)]"
        onChange={(e) => d.setEditedText(e.target.value)}
        value={d.editedText}
      />
      <Input
        className="mt-2 h-8 text-xs"
        onChange={(e) => d.setRevisionReason(e.target.value)}
        placeholder="Motivo de corrección (opcional)"
        value={d.revisionReason}
      />
      {d.saveRevision.isError ? (
        <p className="mt-2 text-xs text-destructive">{d.saveRevision.error.message}</p>
      ) : null}
    </section>
  )
}
