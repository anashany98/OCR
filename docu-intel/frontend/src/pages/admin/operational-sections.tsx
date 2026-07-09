import type { FormEvent } from "react"
import { Link } from "react-router-dom"
import { Activity, AlertTriangle, FileWarning, Network, Pause, Play, RefreshCw } from "lucide-react"

import type {
  AdminAlert,
  BulkReprocessResponse,
  DocumentGraph,
  IngestionEvent,
  OperationsOverview,
  OperationsStatus,
  PaginatedDocuments,
  QueueStatus,
  AuditLog,
} from "@/types/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { StyledSelect } from "@/components/ui/styled-select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useConfirm } from "@/hooks/useConfirm"
import { formatDuration, formatGigabytes, inputFolders, MetricBlock, MetricTile } from "./shared"
import { DOCUMENT_TYPES } from "@/lib/documentTypes"
import type { MutationLike } from "./system-types"

export function SectionHeader({
  icon: Icon,
  title,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
}) {
  return (
    <div className="flex items-center gap-2 pt-2">
      <Icon className="h-4 w-4 text-[var(--accent)]" />
      <h3 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{title}</h3>
      <div className="h-px flex-1 bg-[var(--border)]" />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Alerts section
// ---------------------------------------------------------------------------

export function AlertsSection({ alerts }: { alerts: AdminAlert[] }) {
  return (
    <>
      <SectionHeader icon={AlertTriangle} title="Alertas activas" />
      <Card>
        <CardContent className="space-y-2 pt-4">
          {alerts.map((alert) => (
            <div key={alert.key} className="flex items-start justify-between gap-3 rounded-md border p-3 text-sm">
              <div>
                <div className="flex items-center gap-2">
                  <Badge variant={alert.severity === "critical" ? "destructive" : alert.severity === "warning" ? "warning" : "secondary"}>{alert.count}</Badge>
                  <p className="font-medium">{alert.title}</p>
                </div>
                <p className="mt-1 text-[var(--text-muted)] text-xs">{alert.description}</p>
              </div>
              <Button asChild variant="outline" size="sm"><Link to={alert.action_url}>Abrir</Link></Button>
            </div>
          ))}
          {!alerts.length && <p className="text-sm text-[var(--text-muted)]">Sin alertas operativas activas.</p>}
        </CardContent>
      </Card>
    </>
  )
}

// ---------------------------------------------------------------------------
// Ingestion control section
// ---------------------------------------------------------------------------

export function IngestionControlSection({
  queueStatus,
  pauseQueues,
  resumeQueues,
}: {
  queueStatus?: QueueStatus
  pauseQueues: MutationLike<QueueStatus>
  resumeQueues: MutationLike<QueueStatus>
}) {
  const confirm = useConfirm()
  return (
    <>
      <SectionHeader icon={RefreshCw} title="Control de ingesta" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="grid gap-3 pt-4 md:grid-cols-[1fr_auto_auto]">
            <div className="text-sm">
              <div className="flex flex-wrap gap-2">
                <Badge variant={queueStatus?.ingestion_paused ? "warning" : "success"}>{queueStatus?.ingestion_paused ? "Ingesta pausada" : "Ingesta activa"}</Badge>
                <Badge variant={queueStatus?.backpressure_active ? "warning" : "outline"}>Pendientes: {queueStatus?.pending_jobs ?? 0}/{queueStatus?.max_pending_jobs ?? "-"}</Badge>
                <Badge variant="outline">Procesando: {queueStatus?.processing_jobs ?? 0}</Badge>
              </div>
              <p className="mt-2 text-[var(--text-muted)]">Controla el watchdog y los escaneos masivos.</p>
            </div>
            <Button variant="outline" onClick={async () => { const ok = await confirm({ title: "¿Pausar ingesta?", description: "Se detendrán los nuevos escaneos.", confirmLabel: "Pausar", tone: "danger" }); if (ok) pauseQueues.mutate() }} disabled={pauseQueues.isPending || queueStatus?.ingestion_paused}>
              <Pause data-icon="inline-start" /> Pausar
            </Button>
            <Button variant="outline" onClick={async () => { const ok = await confirm({ title: "¿Reanudar ingesta?", description: "Se reanudarán los escaneos.", confirmLabel: "Reanudar" }); if (ok) resumeQueues.mutate() }} disabled={resumeQueues.isPending || !queueStatus?.ingestion_paused}>
              <Play data-icon="inline-start" /> Reanudar
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex flex-col gap-2 pt-4 text-sm">
            {inputFolders.map((folder) => <code key={folder} className="rounded-md bg-[var(--bg-surface-2)] px-2 py-1 text-xs">{folder}</code>)}
          </CardContent>
        </Card>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Operations center section
// ---------------------------------------------------------------------------

export function OperationsCenterSection({
  operationsOverview,
  operationsStatus,
}: {
  operationsOverview?: OperationsOverview
  operationsStatus?: OperationsStatus
}) {
  return (
    <>
      <SectionHeader icon={Activity} title="Centro de operaciones" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="grid gap-3 pt-4 text-sm sm:grid-cols-4">
            <MetricTile label="GB procesados" value={formatGigabytes(operationsOverview?.documents?.total_size_bytes ?? 0)} />
            <MetricTile label="OCR bajo" value={String(operationsOverview?.documents?.low_ocr_pages ?? 0)} />
            <MetricTile label="Pend/proc." value={String(operationsOverview?.jobs?.pending_or_processing ?? 0)} />
            <MetricTile label="ETA" value={formatDuration(operationsOverview?.jobs?.estimated_remaining_seconds)} />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-3 pt-4 text-sm">
            <MetricBlock title="Jobs" values={operationsStatus?.jobs_by_status} />
            <MetricBlock title="Calidad" values={operationsOverview?.documents?.by_quality_status} />
            <MetricBlock title="Watchdog" values={operationsStatus?.watched_files_by_status} />
          </CardContent>
        </Card>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Bulk reprocess section
// ---------------------------------------------------------------------------

export function BulkReprocessSection({
  status, setStatus, documentType, setDocumentType, sourcePath, setSourcePath, mode, setMode,
  reprocessPending, reprocessResult, reprocessError, onReprocessSubmit,
}: {
  status: string; setStatus: (v: string) => void
  documentType: string; setDocumentType: (v: string) => void
  sourcePath: string; setSourcePath: (v: string) => void
  mode: string; setMode: (v: string) => void
  reprocessPending: boolean; reprocessResult?: BulkReprocessResponse; reprocessError: string | null
  onReprocessSubmit: (e: FormEvent) => void
}) {
  return (
    <>
      <SectionHeader icon={RefreshCw} title="Reprocesado masivo" />
      <Card>
        <CardContent className="pt-4">
          <form className="grid gap-3 md:grid-cols-5" onSubmit={onReprocessSubmit}>
            <StyledSelect value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="failed">Fallidos</option><option value="needs_review">Revisión</option><option value="processed">Procesados</option><option value="pending">Pendientes</option><option value="">Cualquier estado</option>
            </StyledSelect>
            <StyledSelect value={documentType} onChange={(e) => setDocumentType(e.target.value)}>
              <option value="">Cualquier tipo</option>
              {DOCUMENT_TYPES.filter((t) => t.value !== "").map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </StyledSelect>
            <Input value={sourcePath} onChange={(e) => setSourcePath(e.target.value)} placeholder="Carpeta contiene..." />
            <StyledSelect value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="full">Completo</option><option value="ocr">Solo OCR</option><option value="classification">Clasificación</option><option value="embeddings">Embeddings</option>
            </StyledSelect>
            <Button disabled={reprocessPending || (!status && !documentType && !sourcePath)}><RefreshCw data-icon="inline-start" /> Reprocesar</Button>
          </form>
          {reprocessResult && <p className="mt-3 text-sm text-[var(--text-muted)]">Encontrados: {reprocessResult.matched}. Encolados: {reprocessResult.enqueued}.</p>}
          {reprocessError && <p className="mt-3 text-sm text-[var(--danger)]">{reprocessError}</p>}
        </CardContent>
      </Card>
    </>
  )
}

// ---------------------------------------------------------------------------
// Problem documents section
// ---------------------------------------------------------------------------

export function ProblemDocumentsSection({
  operationsDocuments,
  ingestionEvents,
}: {
  operationsDocuments?: PaginatedDocuments
  ingestionEvents: IngestionEvent[]
}) {
  return (
    <>
      <SectionHeader icon={FileWarning} title="Documentos problemáticos" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="pt-4">
            <div className="rounded-md border">
              <Table>
                <TableBody>
                  {(operationsDocuments?.items ?? []).slice(0, 8).map((d) => (
                    <TableRow key={d.id}>
                      <TableCell className="font-mono text-xs">#{d.id}</TableCell>
                      <TableCell className="max-w-[200px] truncate text-xs">{d.original_filename}</TableCell>
                      <TableCell><Badge variant="outline" className="text-[10px]">{d.status}</Badge></TableCell>
                      <TableCell><Badge variant="outline" className="text-[10px]">{d.quality_status}</Badge></TableCell>
                      <TableCell className="text-right"><Button asChild variant="outline" size="sm" className="h-7 text-xs"><Link to={`/documents/${d.id}`}>Ver</Link></Button></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <p className="mt-2 text-xs text-[var(--text-muted)]">Total: {operationsDocuments?.total ?? 0} documentos</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="max-h-52 overflow-auto rounded-md border">
              <Table>
                <TableBody>
                  {ingestionEvents.slice(0, 12).map((e) => (
                    <TableRow key={e.id}>
                      <TableCell><Activity className="size-4 text-[var(--text-muted)]" /></TableCell>
                      <TableCell className="text-xs">{e.event_type}</TableCell>
                      <TableCell className="max-w-[200px] truncate text-xs">{e.source_path ?? "-"}</TableCell>
                      <TableCell className="text-xs text-[var(--text-muted)]">{new Date(e.created_at).toLocaleTimeString()}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Audit & relations section
// ---------------------------------------------------------------------------

export function AuditRelationsSection({
  auditLogs,
  graphDocumentId,
  setGraphDocumentId,
  loadDocumentGraph,
}: {
  auditLogs: AuditLog[]
  graphDocumentId: string
  setGraphDocumentId: (v: string) => void
  loadDocumentGraph: MutationLike<DocumentGraph>
}) {
  return (
    <>
      <SectionHeader icon={Network} title="Auditoría y relaciones" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="pt-4">
            <Table>
              <TableHeader><TableRow><TableHead className="text-xs">Fecha</TableHead><TableHead className="text-xs">Acción</TableHead><TableHead className="text-xs">Entidad</TableHead><TableHead className="text-xs">Usuario</TableHead></TableRow></TableHeader>
              <TableBody>
                {auditLogs.slice(0, 12).map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="text-xs">{new Date(log.created_at).toLocaleString()}</TableCell>
                    <TableCell className="text-xs">{log.action}</TableCell>
                    <TableCell className="text-xs">{log.entity_type ?? "-"} {log.entity_id ?? ""}</TableCell>
                    <TableCell className="text-xs">{log.user_id ?? "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-3 pt-4">
            <form className="grid gap-2 md:grid-cols-[1fr_auto]" onSubmit={(e) => { e.preventDefault(); if (Number(graphDocumentId) > 0) loadDocumentGraph.mutate() }}>
              <Input value={graphDocumentId} onChange={(e) => setGraphDocumentId(e.target.value)} placeholder="ID de documento" className="h-9" />
              <Button disabled={loadDocumentGraph.isPending}><Network data-icon="inline-start" /> Cargar grafo</Button>
            </form>
            {loadDocumentGraph.data && (
              <div className="space-y-2 text-sm">
                <div className="flex gap-2">
                  <Badge variant="neutral">{loadDocumentGraph.data.nodes.length} nodos</Badge>
                  <Badge variant="info">{loadDocumentGraph.data.edges.length} relaciones</Badge>
                </div>
                <div className="max-h-40 overflow-auto rounded-md border">
                  <Table><TableBody>{loadDocumentGraph.data.edges.map((edge, i) => <TableRow key={i}><TableCell className="text-xs">{edge.relation}</TableCell><TableCell className="text-xs">{edge.from_document_id} → {edge.to_document_id}</TableCell><TableCell className="text-xs">{edge.label ?? "-"}</TableCell></TableRow>)}</TableBody></Table>
                </div>
              </div>
            )}
            {loadDocumentGraph.isError && <p className="text-sm text-[var(--danger)]">{loadDocumentGraph.error?.message}</p>}
          </CardContent>
        </Card>
      </div>
    </>
  )
}
