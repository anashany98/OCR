import { type ReactNode, useEffect, useMemo, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  FileSpreadsheet,
  FileText,
  FileWarning,
  Mail,
  MapPin,
  Network,
  RefreshCcw,
  RotateCcw,
  Save,
  Search,
  ShieldAlert,
} from "lucide-react"

import { api, downloadUrl, pageImageUrl, thumbnailUrl } from "@/api/client"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { EmptyState } from "@/components/layout/EmptyState"
import { PermissionGate } from "@/components/layout/PermissionGate"
import { DocumentProgressBar, StatusBadge } from "@/components/layout/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { formatBytes, formatDate, cn } from "@/lib/utils"
import type { DocumentPage, DocumentEntity, DocumentTimelineEvent, DocumentGraph } from "@/types/api"

// ---------------------------------------------------------------------------
// Entity display configuration
// ---------------------------------------------------------------------------
const keyEntities = new Set([
  "invoice_number", "budget_number", "order_number",
  "supplier", "supplier_name", "client", "client_name",
  "total_amount", "amount", "amount_total",
  "date", "invoice_date", "budget_date", "order_date",
  "currency", "reference",
])

function isKeyEntity(entityType: string): boolean {
  return keyEntities.has(entityType) || keyEntities.has(entityType.toLowerCase())
}

function entityLabel(entityType: string): string {
  const labels: Record<string, string> = {
    invoice_number: "Nº Factura",
    budget_number: "Nº Presupuesto",
    order_number: "Nº Pedido",
    supplier: "Proveedor",
    supplier_name: "Proveedor",
    client: "Cliente",
    client_name: "Cliente",
    total_amount: "Importe total",
    amount: "Importe",
    amount_total: "Importe total",
    date: "Fecha",
    invoice_date: "Fecha factura",
    budget_date: "Fecha presupuesto",
    order_date: "Fecha pedido",
    currency: "Moneda",
    reference: "Referencia",
  }
  return labels[entityType] ?? entityType.replace(/_/g, " ")
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export function DocumentDetailPage() {
  const id = Number(useParams().id)
  const queryClient = useQueryClient()
  const [selectedPageNumber, setSelectedPageNumber] = useState<number | null>(null)
  const [textQuery, setTextQuery] = useState("")
  const [editedText, setEditedText] = useState("")
  const [revisionReason, setRevisionReason] = useState("")
  const [showGraph, setShowGraph] = useState(false)
  const [showBlocks, setShowBlocks] = useState(false)

  const doc = useQuery({ queryKey: ["document", id], queryFn: () => api.document(id), enabled: Number.isFinite(id) })
  const pagesQ = useQuery({ queryKey: ["document-pages", id], queryFn: () => api.pages(id), enabled: Number.isFinite(id) })
  const blocksQ = useQuery({ queryKey: ["document-blocks", id], queryFn: () => api.blocks(id), enabled: Number.isFinite(id) })
  const entitiesQ = useQuery({ queryKey: ["document-entities", id], queryFn: () => api.entities(id), enabled: Number.isFinite(id) })
  const timelineQ = useQuery({ queryKey: ["document-timeline", id], queryFn: () => api.documentTimeline(id), enabled: Number.isFinite(id) })
  const graphQ = useQuery({ queryKey: ["document-graph", id], queryFn: () => api.documentGraph(id), enabled: showGraph && Number.isFinite(id) })

  const document = doc.data
  const pages = pagesQ.data ?? []
  const selectedPage = useMemo(
    () => pages.find((p) => p.page_number === selectedPageNumber) ?? pages[0],
    [pages, selectedPageNumber],
  )
  const revisionsQ = useQuery({
    queryKey: ["ocr-revisions", selectedPage?.id],
    queryFn: () => api.ocrRevisions(selectedPage!.id),
    enabled: Boolean(selectedPage),
  })
  const visiblePages = useMemo(() => filterPages(pages, textQuery), [pages, textQuery])
  const entities = entitiesQ.data ?? []
  const keyEnts = entities.filter((e) => isKeyEntity(e.entity_type))
  const otherEnts = entities.filter((e) => !isKeyEntity(e.entity_type))
  const timelineEvents = timelineQ.data ?? []

  const reprocess = useMutation({
    mutationFn: () => api.reprocess(id),
    onSuccess: () => invalidateAll(),
  })
  const saveRevision = useMutation({
    mutationFn: () =>
      api.createOcrRevision(selectedPage!.id, { corrected_text: editedText, reason: revisionReason.trim() || null }),
    onSuccess: () => {
      setRevisionReason("")
      invalidateAll()
    },
  })

  useEffect(() => {
    setEditedText(selectedPage?.text ?? "")
  }, [selectedPage?.id, selectedPage?.text])

  function invalidateAll() {
    ["document", "document-pages", "document-blocks", "document-entities", "document-timeline"].forEach((key) =>
      queryClient.invalidateQueries({ queryKey: [key, id] }),
    )
  }

  const hashShort = document?.file_hash ? `${document.file_hash.slice(0, 10)}...${document.file_hash.slice(-6)}` : "—"

  return (
    <div className="space-y-4">
      {/* Breadcrumbs */}
      <Breadcrumbs
        items={[
          { label: "Documentos", to: "/documents" },
          { label: document?.original_filename ?? "Cargando…" },
        ]}
      />

      {/* ================================================================ */}
      {/* HEADER                                                           */}
      {/* ================================================================ */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3 min-w-0">
              <Button asChild variant="outline" size="icon" className="h-8 w-8 flex-shrink-0" aria-label="Volver al listado">
                <Link to="/documents"><ArrowLeft className="h-4 w-4" aria-hidden="true" /></Link>
              </Button>
              <div className="min-w-0">
                <h1 className="truncate text-[16px] font-semibold text-[var(--text-primary)]">
                  {document?.original_filename ?? "Cargando..."}
                </h1>
                <div className="mt-1.5 flex flex-wrap items-center gap-2">
                  {document?.document_type && (
                    <Badge variant="neutral" className="text-[11px] capitalize">{document.document_type}</Badge>
                  )}
                  {document?.status && <StatusBadge status={document.status} />}
                  {document?.status && (document.status === "uploaded" || document.status === "queued" || document.status === "processing" || document.status === "processed") && (
                    <DocumentProgressBar status={document.status} />
                  )}
                  {document?.quality_status && document.quality_status !== "processed_ok" && (
                    <StatusBadge status={document.quality_status} />
                  )}
                  <ConfidenceBadge value={document?.confidence} />
                  {document?.error_message && (
                    <span className="inline-flex items-center gap-1 rounded bg-[var(--rose-light)] px-2 py-0.5 text-[11px] text-[#9F1239]" title={document.error_message}>
                      <ShieldAlert className="h-3 w-3" />
                      Error
                    </span>
                  )}
                  {document?.duplicate_of_document_id && (
                    <Badge variant="info" className="text-[11px]">Duplicado de #{document.duplicate_of_document_id}</Badge>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)]">
                  {document?.created_at && <span>{formatDate(document.created_at)}</span>}
                  {document?.file_size != null && <span>{formatBytes(document.file_size)}</span>}
                  {document?.mime_type && <span>{document.mime_type}</span>}
                  <span className="font-mono text-[10px] select-all" title={document?.file_hash}>SHA256: {hashShort}</span>
                  {(document?.page_count ?? pages.length) > 0 && <span>{document?.page_count ?? pages.length} páginas</span>}
                </div>
              </div>
            </div>

            {/* Action toolbar */}
            <div className="flex flex-wrap gap-1.5">
              {document?.document_type === "plano" && (
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
                <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => reprocess.mutate()} disabled={reprocess.isPending}>
                  <RefreshCcw className="mr-1 h-3.5 w-3.5" />
                  Reprocesar
                </Button>
              </PermissionGate>
              <PermissionGate roles={["admin", "gestor"]}>
                <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => window.alert("Funcionalidad pendiente de implementar")}>
                  <RotateCcw className="mr-1 h-3.5 w-3.5" />
                  Corregir tipo
                </Button>
              </PermissionGate>
              <PermissionGate roles={["admin", "gestor"]}>
                <Button variant="outline" size="sm" className="h-8 text-xs" onClick={() => window.alert("Funcionalidad pendiente de implementar")}>
                  <FileWarning className="mr-1 h-3.5 w-3.5" />
                  Enviar a revisión
                </Button>
              </PermissionGate>
              <Button asChild size="sm" className="h-8 text-xs">
                <a href={downloadUrl(id)}>
                  <Download className="mr-1 h-3.5 w-3.5" />
                  Descargar
                </a>
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ================================================================ */}
      {/* TWO-COLUMN LAYOUT                                                */}
      {/* ================================================================ */}
      <div className="grid gap-4 xl:grid-cols-2">
        {/* LEFT: Viewer */}
        <Card className="overflow-hidden">
          <CardHeader className="flex-row items-center justify-between border-b bg-slate-50/80 py-3">
            <CardTitle className="text-[14px] font-semibold">Visor</CardTitle>
            {selectedPage && (
              <span className="text-xs text-[var(--text-muted)]">
                Página {selectedPage.page_number} · OCR {selectedPage.ocr_confidence != null ? `${Math.round(selectedPage.ocr_confidence * 100)}%` : "—"}
              </span>
            )}
          </CardHeader>
          <CardContent className="p-0">
            {document && selectedPage?.image_path ? (
              <div className="overflow-hidden bg-slate-100">
                <img
                  className="max-h-[540px] w-full object-contain"
                  src={pageImageUrl(document.id, selectedPage.page_number)}
                  alt={`Página ${selectedPage.page_number}`}
                />
              </div>
            ) : document && hasThumbnail(document.extension) ? (
              <div className="flex justify-center bg-slate-100 py-4">
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
                <EmptyState title="Sin preview visual" description="Este documento no tiene imagen de página disponible." icon={<FileText className="h-5 w-5" />} />
              </div>
            )}
            {pages.length > 1 && (
              <div className="flex flex-wrap gap-1.5 border-t bg-slate-50 px-3 py-2">
                {pages.map((page) => (
                  <Button
                    key={page.id}
                    type="button"
                    size="sm"
                    variant={page.page_number === selectedPage?.page_number ? "default" : "outline"}
                    className="h-7 text-xs"
                    onClick={() => setSelectedPageNumber(page.page_number)}
                  >
                    P{page.page_number}
                  </Button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* RIGHT: OCR + Entities */}
        <div className="space-y-4">
          {/* OCR Text */}
          <Card className="overflow-hidden">
            <CardHeader className="flex-row items-center justify-between border-b bg-slate-50/80 py-3">
              <CardTitle className="text-[14px] font-semibold">Texto OCR</CardTitle>
              <div className="relative w-full max-w-[200px]">
                <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--text-muted)]" />
                <Input
                  className="h-8 pl-7 text-xs"
                  value={textQuery}
                  onChange={(e) => setTextQuery(e.target.value)}
                  placeholder="Buscar en documento..."
                />
              </div>
            </CardHeader>
            <CardContent className="max-h-[460px] overflow-auto p-3">
              <div className="space-y-3">
                {visiblePages.map((page) => (
                  <section key={page.id} className="rounded-md border bg-white p-3">
                    <div className="mb-2 flex justify-between text-[11px] text-[var(--text-muted)]">
                      <button className="font-medium text-[var(--primary)] hover:underline" type="button" onClick={() => setSelectedPageNumber(page.page_number)}>
                        Página {page.page_number}
                      </button>
                      <span>OCR {page.ocr_confidence != null ? `${Math.round(page.ocr_confidence * 100)}%` : "—"}</span>
                    </div>
                    <pre className="whitespace-pre-wrap text-[13px] leading-6 font-sans"><HighlightedText text={page.text || "Sin texto extraído."} query={textQuery} /></pre>
                  </section>
                ))}
                {!visiblePages.length && <EmptyState title="Sin coincidencias" description="No hay páginas que coincidan con la búsqueda actual." />}
              </div>

              {/* OCR Revision editor */}
              {selectedPage && (
                <section className="mt-4 rounded-md border bg-slate-50 p-3">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div>
                      <h4 className="text-[13px] font-semibold">Corrección OCR</h4>
                      <p className="text-[11px] text-[var(--text-muted)]">Página {selectedPage.page_number} · {revisionsQ.data?.length ?? 0} revisiones</p>
                    </div>
                    <Button size="sm" className="h-7 text-xs" onClick={() => saveRevision.mutate()} disabled={saveRevision.isPending || !editedText.trim() || editedText === (selectedPage.text ?? "")}>
                      <Save className="mr-1 h-3 w-3" />Guardar
                    </Button>
                  </div>
                  <textarea
                    className="min-h-[100px] w-full rounded-md border bg-white p-2.5 font-mono text-[12px] leading-6 outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    value={editedText}
                    onChange={(e) => setEditedText(e.target.value)}
                  />
                  <Input className="mt-2 h-8 text-xs" value={revisionReason} onChange={(e) => setRevisionReason(e.target.value)} placeholder="Motivo de corrección (opcional)" />
                  {saveRevision.isError && <p className="mt-2 text-xs text-destructive">{saveRevision.error.message}</p>}
                </section>
              )}
            </CardContent>
          </Card>

          {/* Key Entities */}
          {keyEnts.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-[14px] font-semibold">Entidades clave</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-2 sm:grid-cols-2">
                {keyEnts.map((entity) => (
                  <EntityCard key={entity.id} entity={entity} />
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* ================================================================ */}
      {/* BELOW: Timeline, Graph, All Entities, Blocks                     */}
      {/* ================================================================ */}
      <div className="grid gap-4 xl:grid-cols-2">
        {/* Timeline */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-[14px] font-semibold">Timeline de eventos</CardTitle>
          </CardHeader>
          <CardContent>
            {timelineEvents.length > 0 ? (
              <div className="space-y-1">
                {timelineEvents.map((event, index) => (
                  <TimelineEventRow key={event.id} event={event} isLast={index === timelineEvents.length - 1} />
                ))}
              </div>
            ) : (
              <div className="space-y-1">
                <TimelineEventRow
                  event={{ id: 0, document_id: id, event_type: "registered", title: "Documento registrado", description: null, actor_user_id: null, details_json: null, created_at: document?.created_at ?? "" }}
                  isLast={false}
                />
                {document?.processed_at && (
                  <TimelineEventRow
                    event={{ id: 1, document_id: id, event_type: "processed", title: "Procesamiento completado", description: null, actor_user_id: null, details_json: null, created_at: document.processed_at }}
                    isLast
                  />
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* All entities + blocks summary */}
        <div className="space-y-4">
          {otherEnts.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-[14px] font-semibold">Otras entidades ({otherEnts.length})</CardTitle>
              </CardHeader>
              <CardContent className="max-h-[200px] overflow-auto p-0">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-slate-50 text-left text-[11px] uppercase text-[var(--text-muted)]">
                      <th className="px-3 py-2 font-medium">Tipo</th>
                      <th className="px-3 py-2 font-medium">Valor</th>
                      <th className="px-3 py-2 font-medium text-right">Conf.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {otherEnts.slice(0, 30).map((e) => (
                      <tr key={e.id} className="border-b last:border-0 hover:bg-slate-50">
                        <td className="px-3 py-1.5 text-xs capitalize">{e.entity_type.replace(/_/g, " ")}</td>
                        <td className="max-w-[300px] truncate px-3 py-1.5 text-xs">{e.entity_value}</td>
                        <td className="px-3 py-1.5 text-right text-xs text-[var(--text-muted)]">
                          {e.confidence != null ? `${Math.round(e.confidence * 100)}%` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}

          {/* Collapsible: Blocks */}
          <Card>
            <button
              type="button"
              onClick={() => setShowBlocks(!showBlocks)}
              className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-slate-50/80"
            >
              <CardTitle className="text-[14px] font-semibold">Bloques OCR ({blocksQ.data?.length ?? 0})</CardTitle>
              {showBlocks ? <ChevronDown className="h-4 w-4 text-[var(--text-muted)]" /> : <ChevronRight className="h-4 w-4 text-[var(--text-muted)]" />}
            </button>
            {showBlocks && (
              <CardContent className="max-h-[200px] overflow-auto border-t p-0">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-slate-50 text-left text-[11px] uppercase text-[var(--text-muted)]">
                      <th className="px-3 py-2 font-medium">Pág.</th>
                      <th className="px-3 py-2 font-medium">Tipo</th>
                      <th className="px-3 py-2 font-medium">Texto</th>
                      <th className="px-3 py-2 font-medium text-right">Conf.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(blocksQ.data ?? []).slice(0, 30).map((b) => (
                      <tr key={b.id} className="border-b last:border-0 hover:bg-slate-50">
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
              </CardContent>
            )}
          </Card>

          {/* Collapsible: Document Graph */}
          <Card>
            <button
              type="button"
              onClick={() => setShowGraph(!showGraph)}
              className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-slate-50/80"
            >
              <CardTitle className="text-[14px] font-semibold flex items-center gap-2">
                <Network className="h-4 w-4 text-[var(--text-muted)]" />
                Grafo de relaciones
              </CardTitle>
              {showGraph ? <ChevronDown className="h-4 w-4 text-[var(--text-muted)]" /> : <ChevronRight className="h-4 w-4 text-[var(--text-muted)]" />}
            </button>
            {showGraph && (
              <CardContent className="border-t p-3">
                {graphQ.isLoading && <p className="text-sm text-[var(--text-muted)]">Cargando grafo...</p>}
                {graphQ.data && <DocumentGraphView graph={graphQ.data} />}
                {graphQ.isError && <p className="text-sm text-destructive">{graphQ.error?.message}</p>}
                {!graphQ.data && !graphQ.isLoading && !graphQ.isError && (
                  <EmptyState title="Sin relaciones" description="No se han detectado relaciones documentales para este documento." />
                )}
              </CardContent>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Entity card
// ---------------------------------------------------------------------------
function EntityCard({ entity }: { entity: DocumentEntity }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-md border bg-white px-3 py-2.5">
      <span className="text-[11px] font-medium text-[var(--text-muted)] uppercase tracking-wide">{entityLabel(entity.entity_type)}</span>
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-semibold text-[var(--text-primary)]">{entity.entity_value}</span>
        {entity.confidence != null && (
          <ConfidenceBadge value={entity.confidence} showLabel={false} className="scale-75" />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Timeline event row
// ---------------------------------------------------------------------------
function TimelineEventRow({ event, isLast }: { event: DocumentTimelineEvent; isLast: boolean }) {
  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <span className="mt-1.5 h-2.5 w-2.5 rounded-full border-2 border-[var(--primary)] bg-white flex-shrink-0" />
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
// Document graph view
// ---------------------------------------------------------------------------
function DocumentGraphView({ graph }: { graph: DocumentGraph }) {
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
              <tr className="border-b bg-slate-50 text-left">
                <th className="px-2 py-1.5 font-medium">Relación</th>
                <th className="px-2 py-1.5 font-medium">Desde</th>
                <th className="px-2 py-1.5 font-medium">Hasta</th>
                <th className="px-2 py-1.5 font-medium">Detalle</th>
              </tr>
            </thead>
            <tbody>
              {graph.edges.map((edge, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-slate-50">
                  <td className="px-2 py-1.5 font-medium capitalize">{edge.relation}</td>
                  <td className="px-2 py-1.5">
                    <Link to={`/documents/${edge.from_document_id}`} className="text-[var(--sky)] hover:underline">
                      #{edge.from_document_id}
                    </Link>
                  </td>
                  <td className="px-2 py-1.5">
                    <Link to={`/documents/${edge.to_document_id}`} className="text-[var(--sky)] hover:underline">
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
              "rounded-md border px-2 py-1 text-xs transition-colors hover:bg-slate-50",
              node.document_id === graph.nodes[0].document_id && "border-[var(--primary)] bg-[var(--primary-light)]",
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
// Shared helpers
// ---------------------------------------------------------------------------
function HighlightedText({ text, query }: { text: string; query: string }) {
  const trimmed = query.trim()
  if (!trimmed) return <>{text}</>
  const parts = text.split(new RegExp(`(${escapeRegExp(trimmed)})`, "gi"))
  return (
    <>
      {parts.map((part, index) =>
        part.toLowerCase() === trimmed.toLowerCase() ? (
          <mark key={index} className="rounded bg-amber-200 px-0.5">{part}</mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  )
}

function filterPages(pages: DocumentPage[], query: string) {
  const trimmed = query.trim().toLowerCase()
  if (!trimmed) return pages
  return pages.filter((page) => page.text?.toLowerCase().includes(trimmed))
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

// ---------------------------------------------------------------------------
// Thumbnail support matrix
// ---------------------------------------------------------------------------
const THUMBNAIL_EXTENSIONS = new Set([
  ".pdf",
  ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
  ".xlsx", ".xls", ".xlsm",
  ".msg",
])

function hasThumbnail(extension: string | null | undefined): boolean {
  if (!extension) return false
  return THUMBNAIL_EXTENSIONS.has(extension.toLowerCase())
}

function previewKind(extension: string | null | undefined): "page" | "image" | "excel" | "email" | "other" {
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

// ---------------------------------------------------------------------------
// Fallback card for file types without any preview available
// ---------------------------------------------------------------------------
function UnsupportedPreviewCard({ document }: { document: { id: number; original_filename: string; extension: string | null; file_size: number; file_hash: string; mime_type?: string | null } }) {
  const kind = previewKind(document.extension)
  const Icon = kind === "excel" ? FileSpreadsheet : kind === "email" ? Mail : FileText
  return (
    <div className="flex flex-col items-center gap-4 px-6 py-10">
      <div className="flex h-14 w-14 items-center justify-center rounded-md border bg-slate-50 text-slate-500">
        <Icon className="h-7 w-7" />
      </div>
      <div className="text-center">
        <p className="text-[14px] font-semibold text-[var(--text-primary)]">{typeLabel(document.extension)}</p>
        <p className="mt-1 text-[12px] text-[var(--text-muted)]">
          No hay vista previa disponible para este tipo de archivo. Descárgalo para abrirlo en su aplicación nativa.
        </p>
      </div>
      <dl className="grid w-full max-w-sm grid-cols-2 gap-x-4 gap-y-1.5 rounded-md border bg-slate-50 px-4 py-3 text-[12px]">
        <dt className="text-[var(--text-muted)]">Tipo</dt>
        <dd className="text-right font-mono text-[11px]">{document.extension ?? "—"}</dd>
        <dt className="text-[var(--text-muted)]">Tamaño</dt>
        <dd className="text-right">{formatBytes(document.file_size)}</dd>
        {document.mime_type ? (
          <>
            <dt className="text-[var(--text-muted)]">MIME</dt>
            <dd className="truncate text-right font-mono text-[11px]" title={document.mime_type}>{document.mime_type}</dd>
          </>
        ) : null}
        <dt className="text-[var(--text-muted)]">SHA256</dt>
        <dd className="truncate text-right font-mono text-[11px]" title={document.file_hash}>{document.file_hash.slice(0, 16)}…</dd>
      </dl>
      <Button asChild size="sm" variant="default">
        <a href={downloadUrl(document.id)}>
          <Download className="mr-1 h-3.5 w-3.5" />
          Descargar
        </a>
      </Button>
    </div>
  )
}
