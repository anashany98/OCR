import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { toast } from "sonner"
import {
  ArrowLeft,
  Download,
  FileText,
  FileWarning,
  Info,
  MapPin,
  Network,
  RefreshCcw,
  RotateCcw,
  Save,
  ShieldAlert,
  Type,
} from "lucide-react"

import { documentPreviewUrl, pageImageUrl, thumbnailUrl, downloadUrl } from "@/api/client"
import { AutoBreadcrumbs } from "@/components/layout/AutoBreadcrumbs"
import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { DocumentProgressBar, StatusBadge } from "@/components/layout/StatusBadge"
import { EmptyState } from "@/components/layout/EmptyState"
import { PermissionGate } from "@/components/layout/PermissionGate"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn, formatBytes, formatDate } from "@/lib/utils"
import type { DocumentPage } from "@/types/api"

import {
  BlocksTable,
  CollapsibleCard,
  EntityCard,
  HighlightedText,
  OcrSearchInput,
  OtherEntitiesTable,
  TimelineEventRow,
  UnsupportedPreviewCard,
  VisorCardHeader,
} from "./components"
import { ExcelViewer } from "./ExcelViewer"
import { GraphView } from "./GraphView"
import { useDocumentDetail } from "./useDocumentDetail"

export function DocumentDetailPage() {
  const id = Number(useParams().id)
  const d = useDocumentDetail(id)
  const [activeTab, setActiveTab] = useState("info")

  return (
    <div className="flex h-[calc(100vh-3rem)] flex-col gap-3">
      <AutoBreadcrumbs />
      <DocumentHeader d={d} />

      <div className="flex min-h-0 flex-1 gap-3 lg:flex-row">
        <div className="flex min-w-0 flex-1 flex-col lg:flex-[2]">
          <ViewerCard d={d} />
        </div>

        <div className="flex min-w-0 flex-1 flex-col lg:flex-[1]">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col">
            <TabsList className="w-full justify-start rounded-lg bg-[var(--bg-surface-2)] px-1">
              <TabsTrigger value="info" className="gap-1.5 text-[12px]"><Info className="h-3 w-3" /> Info</TabsTrigger>
              <TabsTrigger value="ocr" className="gap-1.5 text-[12px]"><Type className="h-3 w-3" /> OCR</TabsTrigger>
              <TabsTrigger value="entities" className="gap-1.5 text-[12px]"><ShieldAlert className="h-3 w-3" /> Entidades</TabsTrigger>
              <TabsTrigger value="timeline" className="gap-1.5 text-[12px]"><Network className="h-3 w-3" /> Timeline</TabsTrigger>
            </TabsList>

            <TabsContent value="info" className="mt-2 min-h-0 flex-1 overflow-hidden">
              <ScrollArea className="h-full"><InfoPanel d={d} /></ScrollArea>
            </TabsContent>
            <TabsContent value="ocr" className="mt-2 min-h-0 flex-1 overflow-hidden">
              <ScrollArea className="h-full"><OcrPanel d={d} /></ScrollArea>
            </TabsContent>
            <TabsContent value="entities" className="mt-2 min-h-0 flex-1 overflow-hidden">
              <ScrollArea className="h-full"><EntitiesPanel d={d} /></ScrollArea>
            </TabsContent>
            <TabsContent value="timeline" className="mt-2 min-h-0 flex-1 overflow-hidden">
              <ScrollArea className="h-full"><TimelinePanel d={d} /></ScrollArea>
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  )
}

function DocumentHeader({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const doc = d.document
  return (
    <div className="flex items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-2.5">
      <Button asChild variant="ghost" size="icon" className="h-7 w-7 flex-shrink-0">
        <Link to="/documents"><ArrowLeft className="h-4 w-4" /></Link>
      </Button>
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-[14px] font-semibold text-[var(--text-primary)]">{doc?.original_filename ?? "…"}</h1>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
          {doc?.document_type && <Badge variant="neutral" className="text-[10px] capitalize">{doc.document_type}</Badge>}
          {doc?.status && <StatusBadge status={doc.status} />}
          {doc?.quality_status && doc.quality_status !== "processed_ok" && <StatusBadge status={doc.quality_status} />}
          <ConfidenceBadge value={doc?.confidence} />
          {doc?.error_message && (
            <span className="inline-flex items-center gap-0.5 rounded bg-[var(--danger-light)] px-1.5 py-0.5 text-[10px] text-[var(--text-on-danger)]" title={doc.error_message}>
              <ShieldAlert className="h-2.5 w-2.5" /> Error
            </span>
          )}
          {doc?.created_at && <span className="text-[10px] text-[var(--text-muted)]">{formatDate(doc.created_at)}</span>}
          {doc?.file_size != null && <span className="text-[10px] text-[var(--text-muted)]">{formatBytes(doc.file_size)}</span>}
        </div>
      </div>
      <ActionToolbar d={d} />
    </div>
  )
}

function ActionToolbar({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const id = d.document?.id
  return (
    <div className="flex flex-wrap gap-1">
      {d.document?.document_type === "plano" && id && (
        <PermissionGate roles={["admin", "gestor"]}>
          <Button asChild variant="outline" size="sm" className="h-7 text-[11px]"><Link to={`/documents/${id}/annotate-plan`}><MapPin className="mr-1 h-3 w-3" /> Anotar</Link></Button>
        </PermissionGate>
      )}
      <PermissionGate roles={["admin"]}>
        <Button variant="outline" size="sm" className="h-7 text-[11px]" onClick={() => d.reprocess.mutate()} disabled={d.reprocess.isPending}><RefreshCcw className="mr-1 h-3 w-3" /> Reprocesar</Button>
      </PermissionGate>
      {id && <Button asChild size="sm" className="h-7 text-[11px]"><a href={downloadUrl(id)}><Download className="mr-1 h-3 w-3" /> Descargar</a></Button>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ViewerCard — with error handling for failed images
// ---------------------------------------------------------------------------
function ViewerCard({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const doc = d.document
  const page = d.selectedPage
  const isExcel = [".xlsx", ".xls", ".xlsm"].includes(doc?.extension ?? "")
  const isPdf = doc?.extension?.toLowerCase() === ".pdf"
  const hasOnDemandThumbnail = [
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    ".msg", ".doc", ".docx", ".odt", ".rtf",
  ].includes(doc?.extension?.toLowerCase() ?? "")
  const hasFullGeneratedPreview = [".eml", ".dxf", ".dwg"].includes(doc?.extension?.toLowerCase() ?? "")
  const excelText = isExcel && d.pages.length > 0 ? d.pages.map((p) => p.text || "").join("\n\n") : ""
  const [imgError, setImgError] = useState(false)
  const [thumbError, setThumbError] = useState(false)

  // Reset errors when the selected document or page changes.
  const pageKey = page?.page_number ?? "none"
  useEffect(() => { setImgError(false); setThumbError(false) }, [doc?.id, pageKey])

  return (
    <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <VisorCardHeader>Visor</VisorCardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col p-0">
        <div className="flex min-h-0 flex-1 flex-col">
          {isExcel && excelText ? (
            <div className="flex-1 overflow-auto"><ExcelViewer text={excelText} /></div>
          ) : isPdf && page?.page_number && doc?.id && !imgError ? (
            <div className="flex flex-1 items-center justify-center overflow-auto bg-[var(--bg-surface-2)]">
              <img
                className="max-h-full max-w-full object-contain"
                src={pageImageUrl(doc.id, page.page_number)}
                alt={`Página ${page.page_number}`}
                onError={() => setImgError(true)}
              />
            </div>
          ) : isPdf && imgError ? (
            <FallbackPreview doc={doc} message="No se pudo generar la imagen de esta página. El PDF puede estar dañado o el procesamiento no ha terminado." />
          ) : doc && !thumbError && hasFullGeneratedPreview ? (
            <div className="flex flex-1 items-center justify-center overflow-auto bg-[var(--bg-surface-2)] p-4">
              <img
                className="max-h-full max-w-full rounded object-contain shadow-sm"
                src={documentPreviewUrl(doc.id)}
                alt={`Vista previa de ${doc.original_filename}`}
                onError={() => setThumbError(true)}
              />
            </div>
          ) : doc && !thumbError && hasOnDemandThumbnail ? (
            <div className="flex flex-1 items-center justify-center bg-[var(--bg-surface-2)] p-4">
              <img
                className="max-h-full max-w-full rounded object-contain shadow-sm"
                src={thumbnailUrl(doc.id)}
                alt="Vista previa"
                onError={() => setThumbError(true)}
              />
            </div>
          ) : doc ? (
            <UnsupportedPreviewCard document={doc} />
          ) : (
            <div className="flex flex-1 items-center justify-center"><EmptyState title="Sin preview" description="Sin imagen disponible." icon={<FileText className="h-5 w-5" />} /></div>
          )}
        </div>
        {d.pages.length > 1 && !isExcel && (
          <div className="flex flex-wrap gap-1 border-t border-[var(--border)] bg-[var(--bg-surface-2)] px-3 py-1.5">
            {d.pages.map((p) => (
              <Button key={p.id} type="button" size="sm" variant={p.page_number === page?.page_number ? "default" : "ghost"} className="h-6 px-2 text-[10px]" onClick={() => { d.setSelectedPageNumber(p.page_number); setImgError(false) }}>
                P{p.page_number}
              </Button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function FallbackPreview({ doc, message }: { doc: { original_filename: string; extension?: string | null; file_size: number }; message: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 bg-[var(--bg-surface-2)] p-6 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--bg-surface-3)] text-[var(--text-muted)]">
        <FileText className="h-6 w-6" />
      </div>
      <p className="text-[13px] font-medium text-[var(--text-primary)]">{doc.original_filename}</p>
      <p className="max-w-xs text-[11px] text-[var(--text-muted)]">{message}</p>
      <p className="text-[10px] text-[var(--text-muted)]">{doc.extension} · {formatBytes(doc.file_size)}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Info Panel
// ---------------------------------------------------------------------------
function InfoPanel({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const doc = d.document
  return (
    <div className="space-y-3 p-1">
      <Card>
        <CardContent className="space-y-2 p-3 text-[12px]">
          <div className="grid grid-cols-2 gap-2">
            <InfoRow label="Tipo" value={doc?.document_type ?? "—"} />
            <InfoRow label="Estado" value={doc?.status ?? "—"} />
            <InfoRow label="Calidad" value={doc?.quality_status ?? "—"} />
            <InfoRow label="Páginas" value={String(doc?.page_count ?? d.pages.length)} />
            <InfoRow label="Tamaño" value={doc?.file_size != null ? formatBytes(doc.file_size) : "—"} />
            <InfoRow label="MIME" value={doc?.mime_type ?? "—"} />
            <InfoRow label="Creado" value={doc?.created_at ? formatDate(doc.created_at) : "—"} />
            <InfoRow label="SHA256" value={d.hashShort} mono />
          </div>
        </CardContent>
      </Card>
      {d.keyEnts.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-[13px]">Entidades clave</CardTitle></CardHeader>
          <CardContent className="grid gap-1.5 p-3 pt-0 sm:grid-cols-2">{d.keyEnts.map((e) => <EntityCard key={e.id} entity={e} />)}</CardContent>
        </Card>
      )}
      {d.otherEnts.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-[13px]">Otras entidades ({d.otherEnts.length})</CardTitle></CardHeader>
          <CardContent className="p-0"><OtherEntitiesTable entities={d.otherEnts} /></CardContent>
        </Card>
      )}
    </div>
  )
}

function InfoRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-[var(--text-muted)]">{label}</span>
      <span className={cn("text-right text-[var(--text-primary)]", mono && "font-mono text-[10px]")}>{value}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// OCR Panel
// ---------------------------------------------------------------------------
function OcrPanel({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const page = d.selectedPage
  return (
    <div className="space-y-2 p-1">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[13px] font-semibold">Texto OCR</h3>
        <OcrSearchInput value={d.textQuery} onChange={d.setTextQuery} />
      </div>
      <div className="space-y-2">
        {d.visiblePages.map((p) => (
          <section key={p.id} className="rounded-md border bg-[var(--bg-surface)] p-2.5">
            <div className="mb-1.5 flex justify-between text-[10px] text-[var(--text-muted)]">
              <button className="font-medium text-[var(--accent)] hover:underline" type="button" onClick={() => { d.setSelectedPageNumber(p.page_number); }}>Página {p.page_number}</button>
              <span>OCR {p.ocr_confidence != null ? `${Math.round(p.ocr_confidence * 100)}%` : "—"}</span>
            </div>
            <pre className="whitespace-pre-wrap font-sans text-[12px] leading-5"><HighlightedText text={page?.text || "Sin texto extraído."} query={d.textQuery} /></pre>
          </section>
        ))}
        {!d.visiblePages.length && <EmptyState title="Sin coincidencias" description="No hay páginas que coincidan." />}
      </div>
      {page && (
        <div className="rounded-md border bg-[var(--bg-surface-2)] p-2.5">
          <div className="mb-1.5 flex items-center justify-between">
            <h4 className="text-[12px] font-semibold">Corrección OCR</h4>
            <Button size="sm" className="h-6 text-[10px]" onClick={() => d.saveRevision.mutate()} disabled={d.saveRevision.isPending || !d.editedText.trim() || d.editedText === (page.text ?? "")}><Save className="mr-1 h-2.5 w-2.5" /> Guardar</Button>
          </div>
          <textarea className="min-h-[80px] w-full rounded border bg-[var(--bg-surface)] p-2 font-mono text-[11px] leading-5 outline-none focus:ring-1 focus:ring-[var(--accent)]" value={d.editedText} onChange={(e) => d.setEditedText(e.target.value)} />
          <Input className="mt-1.5 h-7 text-[11px]" value={d.revisionReason} onChange={(e) => d.setRevisionReason(e.target.value)} placeholder="Motivo (opcional)" />
          {d.saveRevision.isError && <p className="mt-1 text-[11px] text-[var(--danger)]">{d.saveRevision.error.message}</p>}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Entities Panel
// ---------------------------------------------------------------------------
function EntitiesPanel({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  return (
    <div className="space-y-2 p-1">
      {d.keyEnts.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-[13px]">Entidades clave</CardTitle></CardHeader>
          <CardContent className="grid gap-1.5 p-3 pt-0 sm:grid-cols-2">{d.keyEnts.map((e) => <EntityCard key={e.id} entity={e} />)}</CardContent>
        </Card>
      )}
      {d.otherEnts.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-[13px]">Otras entidades ({d.otherEnts.length})</CardTitle></CardHeader>
          <CardContent className="p-0"><OtherEntitiesTable entities={d.otherEnts} /></CardContent>
        </Card>
      )}
      <CollapsibleCard title={`Bloques OCR (${d.blocksQ.data?.length ?? 0})`} open={d.showBlocks} onToggle={() => d.setShowBlocks(!d.showBlocks)}>
        <BlocksTable blocks={d.blocksQ.data ?? []} />
      </CollapsibleCard>
      <CollapsibleCard title="Grafo de relaciones" icon={<Network className="h-4 w-4 text-[var(--text-muted)]" />} open={d.showGraph} onToggle={() => d.setShowGraph(!d.showGraph)}>
        {d.graphQ.isLoading && <p className="text-[12px] text-[var(--text-muted)]">Cargando...</p>}
        {d.graphQ.data && <GraphView graph={d.graphQ.data} currentDocId={d.document?.id} />}
        {d.graphQ.isError && <p className="text-[12px] text-[var(--danger)]">{d.graphQ.error?.message}</p>}
        {!d.graphQ.data && !d.graphQ.isLoading && !d.graphQ.isError && <EmptyState title="Sin relaciones" description="No se detectaron relaciones." />}
      </CollapsibleCard>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Timeline Panel
// ---------------------------------------------------------------------------
function TimelinePanel({ d }: { d: ReturnType<typeof useDocumentDetail> }) {
  const id = d.document?.id
  return (
    <div className="space-y-2 p-1">
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-[13px]">Timeline</CardTitle></CardHeader>
        <CardContent>
          {d.timelineEvents.length > 0 ? (
            <div className="space-y-0.5">{d.timelineEvents.map((e, i) => <TimelineEventRow key={e.id} event={e} isLast={i === d.timelineEvents.length - 1} />)}</div>
          ) : (
            <div className="space-y-0.5">
              <TimelineEventRow event={{ id: 0, document_id: id ?? 0, event_type: "registered", title: "Documento registrado", description: null, actor_user_id: null, details_json: null, created_at: d.document?.created_at ?? "" }} isLast={!d.document?.processed_at} />
              {d.document?.processed_at && <TimelineEventRow event={{ id: 1, document_id: id ?? 0, event_type: "processed", title: "Procesamiento completado", description: null, actor_user_id: null, details_json: null, created_at: d.document.processed_at }} isLast />}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
