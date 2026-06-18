import type { FormEvent } from "react"
import { Link } from "react-router-dom"
import { Activity, AlertTriangle, FileWarning, Network, Pause, Play, RefreshCw } from "lucide-react"

import type {
  AdminAlert,
  AdminStats,
  AuditLog,
  BulkReprocessResponse,
  DocumentGraph,
  IngestionEvent,
  MaintenanceReport,
  OperationsOverview,
  OperationsStatus,
  PaginatedDocuments,
  ProcessingMetrics,
  QueueStatus,
  WatchedFile,
} from "@/types/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { formatDuration, formatGigabytes, inputFolders, MetricBlock, MetricTile } from "./shared"
import { useAdminOperationalData } from "./useAdminOperationalData"
import { useAdminReprocess } from "./useAdminReprocess"

interface MutationLike<TData = unknown> {
  mutate: () => void
  isPending: boolean
  data?: TData
  isError: boolean
  error: Error | null
}

interface OperationalViewProps {
  auditLogs: AuditLog[]
  alerts: AdminAlert[]
  metrics?: ProcessingMetrics
  queueStatus?: QueueStatus
  operationsOverview?: OperationsOverview
  operationsStatus?: OperationsStatus
  maintenanceReport?: MaintenanceReport
  operationsDocuments?: PaginatedDocuments
  watchedFiles: WatchedFile[]
  ingestionEvents: IngestionEvent[]
  stats?: AdminStats
  status: string
  setStatus: (v: string) => void
  documentType: string
  setDocumentType: (v: string) => void
  sourcePath: string
  setSourcePath: (v: string) => void
  mode: string
  setMode: (v: string) => void
  reprocessPending: boolean
  reprocessResult?: BulkReprocessResponse
  reprocessError: string | null
  onReprocessSubmit: (e: FormEvent) => void
  pauseQueues: MutationLike<QueueStatus>
  resumeQueues: MutationLike<QueueStatus>
  graphDocumentId: string
  setGraphDocumentId: (v: string) => void
  loadDocumentGraph: MutationLike<DocumentGraph>
}

function OperationalView(props: OperationalViewProps) {
  const {
    alerts,
    queueStatus,
    pauseQueues,
    resumeQueues,
    operationsOverview,
    operationsStatus,
    operationsDocuments,
    ingestionEvents,
    auditLogs,
    status,
    setStatus,
    documentType,
    setDocumentType,
    sourcePath,
    setSourcePath,
    mode,
    setMode,
    reprocessPending,
    reprocessResult,
    reprocessError,
    onReprocessSubmit,
    graphDocumentId,
    setGraphDocumentId,
    loadDocumentGraph,
  } = props

  return (
    <div className="space-y-6">
      <SectionHeader icon={AlertTriangle} title="Alertas activas" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="xl:col-span-2">
          <CardContent className="space-y-2 pt-4">
            {alerts.map((alert) => (
              <div
                key={alert.key}
                className="flex items-start justify-between gap-3 rounded-md border p-3 text-sm"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <Badge
                      variant={
                        alert.severity === "critical"
                          ? "destructive"
                          : alert.severity === "warning"
                            ? "warning"
                            : "secondary"
                      }
                    >
                      {alert.count}
                    </Badge>
                    <p className="font-medium">{alert.title}</p>
                  </div>
                  <p className="mt-1 text-muted-foreground text-xs">{alert.description}</p>
                </div>
                <Button asChild variant="outline" size="sm">
                  <Link to={alert.action_url}>Abrir</Link>
                </Button>
              </div>
            ))}
            {!alerts.length && (
              <p className="text-sm text-muted-foreground">Sin alertas operativas activas.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <SectionHeader icon={RefreshCw} title="Control de ingesta" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="grid gap-3 pt-4 md:grid-cols-[1fr_auto_auto]">
            <div className="text-sm">
              <div className="flex flex-wrap gap-2">
                <Badge variant={queueStatus?.ingestion_paused ? "warning" : "success"}>
                  {queueStatus?.ingestion_paused ? "Ingesta pausada" : "Ingesta activa"}
                </Badge>
                <Badge variant={queueStatus?.backpressure_active ? "warning" : "outline"}>
                  Pendientes: {queueStatus?.pending_jobs ?? 0}/
                  {queueStatus?.max_pending_jobs ?? "-"}
                </Badge>
                <Badge variant="outline">Procesando: {queueStatus?.processing_jobs ?? 0}</Badge>
              </div>
              <p className="mt-2 text-muted-foreground">
                Controla el watchdog y los escaneos masivos.
              </p>
            </div>
            <Button
              variant="outline"
              onClick={() => {
                if (window.confirm("¿Pausar?")) pauseQueues.mutate()
              }}
              disabled={pauseQueues.isPending || queueStatus?.ingestion_paused}
            >
              <Pause data-icon="inline-start" />
              Pausar
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                if (window.confirm("¿Reanudar?")) resumeQueues.mutate()
              }}
              disabled={resumeQueues.isPending || !queueStatus?.ingestion_paused}
            >
              <Play data-icon="inline-start" />
              Reanudar
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex flex-col gap-2 pt-4 text-sm">
            {inputFolders.map((folder) => (
              <code key={folder} className="rounded-md bg-muted px-2 py-1 text-xs">
                {folder}
              </code>
            ))}
          </CardContent>
        </Card>
      </div>

      <SectionHeader icon={Activity} title="Centro de operaciones" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="grid gap-3 pt-4 text-sm sm:grid-cols-4">
            <MetricTile
              label="GB procesados"
              value={formatGigabytes(operationsOverview?.documents?.total_size_bytes ?? 0)}
            />
            <MetricTile
              label="OCR bajo"
              value={String(operationsOverview?.documents?.low_ocr_pages ?? 0)}
            />
            <MetricTile
              label="Pend/proc."
              value={String(operationsOverview?.jobs?.pending_or_processing ?? 0)}
            />
            <MetricTile
              label="ETA"
              value={formatDuration(operationsOverview?.jobs?.estimated_remaining_seconds)}
            />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-3 pt-4 text-sm">
            <MetricBlock title="Jobs" values={operationsStatus?.jobs_by_status} />
            <MetricBlock
              title="Calidad"
              values={operationsOverview?.documents?.by_quality_status}
            />
            <MetricBlock title="Watchdog" values={operationsStatus?.watched_files_by_status} />
          </CardContent>
        </Card>
      </div>

      <SectionHeader icon={RefreshCw} title="Reprocesado masivo" />
      <div className="grid gap-4">
        <Card>
          <CardContent className="pt-4">
            <form className="grid gap-3 md:grid-cols-5" onSubmit={onReprocessSubmit}>
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="failed">Fallidos</option>
                <option value="needs_review">Revisión</option>
                <option value="processed">Procesados</option>
                <option value="pending">Pendientes</option>
                <option value="">Cualquier estado</option>
              </select>
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={documentType}
                onChange={(e) => setDocumentType(e.target.value)}
              >
                <option value="">Cualquier tipo</option>
                <option value="presupuesto">Presupuesto</option>
                <option value="pedido">Pedido</option>
                <option value="factura">Factura</option>
                <option value="plano">Plano</option>
                <option value="imagen">Imagen</option>
                <option value="excel">Excel</option>
              </select>
              <Input
                value={sourcePath}
                onChange={(e) => setSourcePath(e.target.value)}
                placeholder="Carpeta contiene..."
              />
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={mode}
                onChange={(e) => setMode(e.target.value)}
              >
                <option value="full">Completo</option>
                <option value="ocr">Solo OCR</option>
                <option value="classification">Clasificación</option>
                <option value="embeddings">Embeddings</option>
              </select>
              <Button disabled={reprocessPending || (!status && !documentType && !sourcePath)}>
                <RefreshCw data-icon="inline-start" />
                Reprocesar
              </Button>
            </form>
            {reprocessResult && (
              <p className="mt-3 text-sm text-muted-foreground">
                Encontrados: {reprocessResult.matched}. Encolados: {reprocessResult.enqueued}.
              </p>
            )}
            {reprocessError && <p className="mt-3 text-sm text-destructive">{reprocessError}</p>}
          </CardContent>
        </Card>
      </div>

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
                      <TableCell className="max-w-[200px] truncate text-xs">
                        {d.original_filename}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-[10px]">
                          {d.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-[10px]">
                          {d.quality_status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button asChild variant="outline" size="sm" className="h-7 text-xs">
                          <Link to={`/documents/${d.id}`}>Ver</Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Total: {operationsDocuments?.total ?? 0} documentos
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="max-h-52 overflow-auto rounded-md border">
              <Table>
                <TableBody>
                  {ingestionEvents.slice(0, 12).map((e) => (
                    <TableRow key={e.id}>
                      <TableCell>
                        <Activity className="size-4 text-muted-foreground" />
                      </TableCell>
                      <TableCell className="text-xs">{e.event_type}</TableCell>
                      <TableCell className="max-w-[200px] truncate text-xs">
                        {e.source_path ?? "-"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {new Date(e.created_at).toLocaleTimeString()}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>

      <SectionHeader icon={Network} title="Auditoría y relaciones" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="pt-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">Fecha</TableHead>
                  <TableHead className="text-xs">Acción</TableHead>
                  <TableHead className="text-xs">Entidad</TableHead>
                  <TableHead className="text-xs">Usuario</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {auditLogs.slice(0, 12).map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="text-xs">
                      {new Date(log.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-xs">{log.action}</TableCell>
                    <TableCell className="text-xs">
                      {log.entity_type ?? "-"} {log.entity_id ?? ""}
                    </TableCell>
                    <TableCell className="text-xs">{log.user_id ?? "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-3 pt-4">
            <form
              className="grid gap-2 md:grid-cols-[1fr_auto]"
              onSubmit={(e) => {
                e.preventDefault()
                if (Number(graphDocumentId) > 0) loadDocumentGraph.mutate()
              }}
            >
              <Input
                value={graphDocumentId}
                onChange={(e) => setGraphDocumentId(e.target.value)}
                placeholder="ID de documento"
                className="h-9"
              />
              <Button disabled={loadDocumentGraph.isPending}>
                <Network data-icon="inline-start" />
                Cargar grafo
              </Button>
            </form>
            {loadDocumentGraph.data && (
              <div className="space-y-2 text-sm">
                <div className="flex gap-2">
                  <Badge variant="neutral">{loadDocumentGraph.data.nodes.length} nodos</Badge>
                  <Badge variant="info">{loadDocumentGraph.data.edges.length} relaciones</Badge>
                </div>
                <div className="max-h-40 overflow-auto rounded-md border">
                  <Table>
                    <TableBody>
                      {loadDocumentGraph.data.edges.map((edge, i) => (
                        <TableRow key={i}>
                          <TableCell className="text-xs">{edge.relation}</TableCell>
                          <TableCell className="text-xs">
                            {edge.from_document_id} → {edge.to_document_id}
                          </TableCell>
                          <TableCell className="text-xs">{edge.label ?? "-"}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            )}
            {loadDocumentGraph.isError && (
              <p className="text-sm text-destructive">{loadDocumentGraph.error?.message}</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function SectionHeader({
  icon: Icon,
  title,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
}) {
  return (
    <div className="flex items-center gap-2 pt-2">
      <Icon className="h-4 w-4 text-[var(--primary)]" />
      <h3 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
        {title}
      </h3>
      <div className="h-px flex-1 bg-[var(--border)]" />
    </div>
  )
}

/**
 * F4b - Operational admin sub-page. Lazy-loaded via the router.
 *
 * Mounts ``useAdminOperationalData`` so this tab fetches only its
 * own queries. The bulk-reprocess filters are kept in local state
 * and published into ``AdminReprocessContext`` so the shell's
 * confirm dialog can read them.
 */
export function AdminOperationalPage() {
  const { state, queries, mutations, handlers, reprocessContextValue, AdminReprocessContext } =
    useAdminOperationalData()
  const { reprocess } = useAdminReprocess()

  return (
    <AdminReprocessContext.Provider value={reprocessContextValue}>
      <OperationalView
        auditLogs={queries.auditLogs.data ?? []}
        alerts={queries.alerts.data ?? []}
        metrics={queries.metrics.data}
        queueStatus={queries.queueStatus.data}
        operationsOverview={queries.operationsOverview.data}
        operationsStatus={queries.operationsStatus.data}
        maintenanceReport={queries.maintenanceReport.data}
        operationsDocuments={queries.operationsDocuments.data}
        watchedFiles={queries.watchedFiles.data ?? []}
        ingestionEvents={queries.ingestionEvents.data ?? []}
        stats={queries.stats.data}
        status={state.status}
        setStatus={state.setStatus}
        documentType={state.documentType}
        setDocumentType={state.setDocumentType}
        sourcePath={state.sourcePath}
        setSourcePath={state.setSourcePath}
        mode={state.mode}
        setMode={state.setMode}
        reprocessPending={reprocess.isPending}
        reprocessResult={reprocess.data}
        reprocessError={reprocess.isError ? (reprocess.error as Error).message : null}
        onReprocessSubmit={handlers.onReprocessSubmit}
        pauseQueues={{
          mutate: () => mutations.pauseQueues.mutate(),
          isPending: mutations.pauseQueues.isPending,
          data: mutations.pauseQueues.data,
          isError: mutations.pauseQueues.isError,
          error: mutations.pauseQueues.error,
        }}
        resumeQueues={{
          mutate: () => mutations.resumeQueues.mutate(),
          isPending: mutations.resumeQueues.isPending,
          data: mutations.resumeQueues.data,
          isError: mutations.resumeQueues.isError,
          error: mutations.resumeQueues.error,
        }}
        graphDocumentId={state.graphDocumentId}
        setGraphDocumentId={state.setGraphDocumentId}
        loadDocumentGraph={{
          mutate: () => mutations.loadDocumentGraph.mutate(),
          isPending: mutations.loadDocumentGraph.isPending,
          data: mutations.loadDocumentGraph.data,
          isError: mutations.loadDocumentGraph.isError,
          error: mutations.loadDocumentGraph.error,
        }}
      />
    </AdminReprocessContext.Provider>
  )
}
