import { Link, useParams } from "react-router-dom"
import { toast } from "sonner"
import {
  ArrowLeft,
  Download,
  FileText,
  FileWarning,
  MapPin,
  Network,
  RefreshCcw,
  RotateCcw,
  Save,
  ShieldAlert,
} from "lucide-react"

import { pageImageUrl, thumbnailUrl, downloadUrl } from "@/api/client"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { DocumentProgressBar, StatusBadge } from "@/components/layout/StatusBadge"
import { EmptyState } from "@/components/layout/EmptyState"
import { PermissionGate } from "@/components/layout/PermissionGate"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { formatBytes, formatDate } from "@/lib/utils"
import type { DocumentPage } from "@/types/api"

import {
  BlocksTable,
  CollapsibleCard,
  DocumentGraphView,
  EntityCard,
  HighlightedText,
  OcrSearchInput,
  OtherEntitiesTable,
  TimelineEventRow,
  UnsupportedPreviewCard,
  VisorCardHeader,
} from "./components"
import { ExcelViewer } from "./ExcelViewer"
import { useDocumentDetail } from "./useDocumentDetail"

// ---------------------------------------------------------------------------
// F8b-cont2 - document detail page composition
//
// The previous file was 34 KB / 704 lines mixing data fetching,
// local UI state, a search input, an OCR revision editor, a
// viewer card, a key-entities card, a timeline, a collapsible
// blocks table, a collapsible graph view and inline
// sub-components (EntityCard, TimelineEventRow,
// DocumentGraphView, UnsupportedPreviewCard,
// HighlightedText).
//
// After F8b-cont2:
// - useDocumentDetail() owns every piece of state and side
//   effect (queries, draft, mutations, helpers);
// - AnnotationSidebar / plan components were already
//   extracted earlier;
// - Components.tsx provides HighlightedText, EntityCard,
//   TimelineEventRow, DocumentGraphView,
//   UnsupportedPreviewCard, OcrSearchInput,
//   CollapsibleCard, BlocksTable, OtherEntitiesTable and
//   VisorCardHeader;
// - this file is the layout shell: header, two-column
//   viewer+text row, second row with timeline + (other
//   entities, blocks, graph).
// ---------------------------------------------------------------------------
export function DocumentDetailPage() {
  const id = Number(useParams().id)
  const d = useDocumentDetail(id)

  return (
    <div className="space-y-4">
      <Breadcrumbs
        items={[
          { label: "Documentos", to: "/documents" },
          { label: d.document?.original_filename ?? "Cargando…" },
        ]}
      />

      <DocumentHeader d={d} />

      <div className="grid gap-4 xl:grid-cols-2">
        <ViewerCard d={d} />
        <div className="space-y-4">
          <OcrCard d={d} />
          {d.keyEnts.length > 0 && <KeyEntitiesCard entities={d.keyEnts} />}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <TimelineCard d={d} />
        <BelowSection d={d} />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// DocumentHeader
// ---------------------------------------------------------------------------
function DocumentHeader({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const document = d.document
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <Button
              asChild
              variant="outline"
              size="icon"
              className="h-8 w-8 flex-shrink-0"
              aria-label="Volver al listado"
            >
              <Link to="/documents">
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              </Link>
            </Button>
            <div className="min-w-0">
              <h1 className="truncate text-[16px] font-semibold text-[var(--text-primary)]">
                {document?.original_filename ?? "Cargando..."}
              </h1>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                {document?.document_type && (
                  <Badge variant="neutral" className="text-[11px] capitalize">
                    {document.document_type}
                  </Badge>
                )}
                {document?.status && <StatusBadge status={document.status} />}
                {document?.status &&
                  (document.status === "uploaded" ||
                    document.status === "queued" ||
                    document.status === "processing" ||
                    document.status === "processed") && (
                    <DocumentProgressBar status={document.status} />
                  )}
                {document?.quality_status && document.quality_status !== "processed_ok" && (
                  <StatusBadge status={document.quality_status} />
                )}
                <ConfidenceBadge value={document?.confidence} />
                {document?.error_message && (
                  <span
                    className="inline-flex items-center gap-1 rounded bg-[var(--rose-light)] px-2 py-0.5 text-[11px] text-[var(--text-on-danger)]"
                    title={document.error_message}
                  >
                    <ShieldAlert className="h-3 w-3" />
                    Error
                  </span>
                )}
                {document?.duplicate_of_document_id && (
                  <Badge variant="info" className="text-[11px]">
                    Duplicado de #{document.duplicate_of_document_id}
                  </Badge>
                )}
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)]">
                {document?.created_at && <span>{formatDate(document.created_at)}</span>}
                {document?.file_size != null && <span>{formatBytes(document.file_size)}</span>}
                {document?.mime_type && <span>{document.mime_type}</span>}
                <span className="select-all font-mono text-[10px]" title={document?.file_hash}>
                  SHA256: {d.hashShort}
                </span>
                {(document?.page_count ?? d.pages.length) > 0 && (
                  <span>{document?.page_count ?? d.pages.length} páginas</span>
                )}
              </div>
            </div>
          </div>

          <ActionToolbar d={d} />
        </div>
      </CardContent>
    </Card>
  )
}

function ActionToolbar({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const id = d.document?.id
  return (
    <div className="flex flex-wrap gap-1.5">
      {d.document?.document_type === "plano" && id && (
        <PermissionGate roles={["admin", "gestor"]}>
          <Button asChild variant="outline" size="sm" className="h-8 text-xs">
            <Link to={`/documents/${id}/annotate-plan`}>
              <MapPin className="mr-1 h-3.5 w-3.5" />
              Anotar plano
            </Link>
          </Button>
        </PermissionGate>
      )}
      <PermissionGate roles={["admin"]}>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          onClick={() => d.reprocess.mutate()}
          disabled={d.reprocess.isPending}
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
          onClick={() => toast.info("Funcionalidad próximamente")}
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
          onClick={() => toast.info("Funcionalidad próximamente")}
        >
          <FileWarning className="mr-1 h-3.5 w-3.5" />
          Enviar a revisión
        </Button>
      </PermissionGate>
      {id && (
        <Button asChild size="sm" className="h-8 text-xs">
          <a href={downloadUrl(id)}>
            <Download className="mr-1 h-3.5 w-3.5" />
            Descargar
          </a>
        </Button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ViewerCard
// ---------------------------------------------------------------------------
function ViewerCard({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const document = d.document
  const page = d.selectedPage
  const isExcel = [".xlsx", ".xls", ".xlsm"].includes(document?.extension ?? "")
  const excelText = isExcel && d.pages.length > 0 ? d.pages.map((p) => p.text || "").join("\n\n") : ""

  return (
    <Card className="overflow-hidden">
      <VisorCardHeader>Visor</VisorCardHeader>
      <CardContent className="p-0">
        {isExcel && excelText ? (
          <div className="max-h-[540px] overflow-auto">
            <ExcelViewer text={excelText} />
          </div>
        ) : page?.page_number && document?.id ? (
          <div className="overflow-hidden bg-[var(--bg-surface-2)]">
            <img
              className="max-h-[540px] w-full object-contain"
              src={pageImageUrl(document.id, page.page_number)}
              alt={`Página ${page.page_number}`}
            />
          </div>
        ) : document && d.hasThumbnailExt ? (
          <div className="flex justify-center bg-[var(--bg-surface-2)] py-4">
            <img
              className="max-h-[540px] max-w-full rounded-md object-contain shadow-md"
              src={thumbnailUrl(document.id)}
              alt="Vista previa del documento"
            />
          </div>
        ) : document ? (
          <UnsupportedPreviewCard document={document} />
        ) : (
          <div className="flex items-center justify-center py-16">
            <EmptyState
              title="Sin preview visual"
              description="Este documento no tiene imagen de página disponible."
              icon={<FileText className="h-5 w-5" />}
            />
          </div>
        )}
        {d.pages.length > 1 && !isExcel && (
          <div className="flex flex-wrap gap-1.5 border-t bg-[var(--bg-surface-2)] px-3 py-2">
            {d.pages.map((p) => (
              <Button
                key={p.id}
                type="button"
                size="sm"
                variant={p.page_number === page?.page_number ? "default" : "outline"}
                className="h-7 text-xs"
                onClick={() => d.setSelectedPageNumber(p.page_number)}
              >
                P{p.page_number}
              </Button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// OcrCard
// ---------------------------------------------------------------------------
function OcrCard({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const page = d.selectedPage
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-center justify-between border-b bg-[var(--bg-surface-2)]/80 py-3">
        <CardTitle className="text-[14px] font-semibold">Texto OCR</CardTitle>
        <OcrSearchInput value={d.textQuery} onChange={d.setTextQuery} />
      </CardHeader>
      <CardContent className="max-h-[460px] overflow-auto p-3">
        <div className="space-y-3">
          {d.visiblePages.map((p) => (
            <OcrPageSection
              key={p.id}
              page={p}
              query={d.textQuery}
              onPick={() => d.setSelectedPageNumber(p.page_number)}
            />
          ))}
          {!d.visiblePages.length && (
            <EmptyState
              title="Sin coincidencias"
              description="No hay páginas que coincidan con la búsqueda actual."
            />
          )}
        </div>
        {page && <OcrRevisionEditor d={d} />}
      </CardContent>
    </Card>
  )
}

function OcrPageSection({
  page,
  query,
  onPick,
}: {
  page: DocumentPage
  query: string
  onPick: () => void
}) {
  return (
    <section className="rounded-md border bg-[var(--bg-surface)] p-3">
      <div className="mb-2 flex justify-between text-[11px] text-[var(--text-muted)]">
        <button
          className="font-medium text-[var(--primary)] hover:underline"
          type="button"
          onClick={onPick}
        >
          Página {page.page_number}
        </button>
        <span>
          OCR {page.ocr_confidence != null ? `${Math.round(page.ocr_confidence * 100)}%` : "—"}
        </span>
      </div>
      <pre className="whitespace-pre-wrap font-sans text-[13px] leading-6">
        <HighlightedText text={page.text || "Sin texto extraído."} query={query} />
      </pre>
    </section>
  )
}

function OcrRevisionEditor({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
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
          onClick={() => d.saveRevision.mutate()}
          disabled={
            d.saveRevision.isPending || !d.editedText.trim() || d.editedText === (page.text ?? "")
          }
        >
          <Save className="mr-1 h-3 w-3" />
          Guardar
        </Button>
      </div>
      <textarea
        className="min-h-[100px] w-full rounded-md border bg-[var(--bg-surface)] p-2.5 font-mono text-[12px] leading-6 outline-none focus:ring-2 focus:ring-[var(--primary)]"
        value={d.editedText}
        onChange={(e) => d.setEditedText(e.target.value)}
      />
      <Input
        className="mt-2 h-8 text-xs"
        value={d.revisionReason}
        onChange={(e) => d.setRevisionReason(e.target.value)}
        placeholder="Motivo de corrección (opcional)"
      />
      {d.saveRevision.isError && (
        <p className="mt-2 text-xs text-destructive">{d.saveRevision.error.message}</p>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// KeyEntitiesCard
// ---------------------------------------------------------------------------
function KeyEntitiesCard({
  entities,
}: {
  entities: ReturnType<typeof useDocumentDetail>["keyEnts"]
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-[14px] font-semibold">Entidades clave</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2 sm:grid-cols-2">
        {entities.map((entity) => (
          <EntityCard key={entity.id} entity={entity} />
        ))}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// TimelineCard
// ---------------------------------------------------------------------------
function TimelineCard({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const id = d.document?.id
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-[14px] font-semibold">Timeline de eventos</CardTitle>
      </CardHeader>
      <CardContent>
        {d.timelineEvents.length > 0 ? (
          <div className="space-y-1">
            {d.timelineEvents.map((event, index) => (
              <TimelineEventRow
                key={event.id}
                event={event}
                isLast={index === d.timelineEvents.length - 1}
              />
            ))}
          </div>
        ) : (
          <div className="space-y-1">
            <TimelineEventRow
              event={{
                id: 0,
                document_id: id ?? 0,
                event_type: "registered",
                title: "Documento registrado",
                description: null,
                actor_user_id: null,
                details_json: null,
                created_at: d.document?.created_at ?? "",
              }}
              isLast={false}
            />
            {d.document?.processed_at && (
              <TimelineEventRow
                event={{
                  id: 1,
                  document_id: id ?? 0,
                  event_type: "processed",
                  title: "Procesamiento completado",
                  description: null,
                  actor_user_id: null,
                  details_json: null,
                  created_at: d.document.processed_at,
                }}
                isLast
              />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// BelowSection — other entities, blocks, graph
// ---------------------------------------------------------------------------
function BelowSection({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  return (
    <div className="space-y-4">
      {d.otherEnts.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-[14px] font-semibold">
              Otras entidades ({d.otherEnts.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <OtherEntitiesTable entities={d.otherEnts} />
          </CardContent>
        </Card>
      )}

      <CollapsibleCard
        title={`Bloques OCR (${d.blocksQ.data?.length ?? 0})`}
        open={d.showBlocks}
        onToggle={() => d.setShowBlocks(!d.showBlocks)}
      >
        <BlocksTable blocks={d.blocksQ.data ?? []} />
      </CollapsibleCard>

      <CollapsibleCard
        title="Grafo de relaciones"
        icon={<Network className="h-4 w-4 text-[var(--text-muted)]" />}
        open={d.showGraph}
        onToggle={() => d.setShowGraph(!d.showGraph)}
      >
        {d.graphQ.isLoading && (
          <p className="text-sm text-[var(--text-muted)]">Cargando grafo...</p>
        )}
        {d.graphQ.data && <DocumentGraphView graph={d.graphQ.data} />}
        {d.graphQ.isError && <p className="text-sm text-destructive">{d.graphQ.error?.message}</p>}
        {!d.graphQ.data && !d.graphQ.isLoading && !d.graphQ.isError && (
          <EmptyState
            title="Sin relaciones"
            description="No se han detectado relaciones documentales para este documento."
          />
        )}
      </CollapsibleCard>
    </div>
  )
}
