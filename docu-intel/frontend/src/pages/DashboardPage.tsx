import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, Clock, FileWarning, Inbox, Layers3, RefreshCw } from "lucide-react"

import { api } from "@/api/client"
import { ActionPanel } from "@/components/layout/ActionPanel"
import { EmptyState } from "@/components/layout/EmptyState"
import { MetricTile } from "@/components/layout/MetricTile"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Badge, type BadgeProps } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { buildTodaySnapshot, workInboxTarget } from "@/lib/operations"
import { severityTone } from "@/lib/status"

export function DashboardPage() {
  const { data, isLoading } = useQuery({ queryKey: ["stats"], queryFn: api.stats })
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts })
  const metrics = useQuery({ queryKey: ["processing-metrics"], queryFn: api.processingMetrics })
  const overview = useQuery({ queryKey: ["operations-overview"], queryFn: api.operationsOverview, refetchInterval: 15000 })
  const inbox = useQuery({ queryKey: ["work-inbox", "dashboard"], queryFn: () => api.workInbox({ limit: 8 }), refetchInterval: 15000 })
  const snapshot = buildTodaySnapshot({ stats: data, alerts: alerts.data, inbox: inbox.data, overview: overview.data })
  const topAlerts = (alerts.data ?? []).slice(0, 4)
  const topInbox = (inbox.data ?? []).slice(0, 6)

  return (
    <>
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
        <PageHeader title="Hoy" description="Estado operativo, trabajo pendiente y señales de riesgo para la jornada." />
        <div className="flex gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to="/documents">
              <Layers3 data-icon="inline-start" />
              Documentos
            </Link>
          </Button>
          <Button asChild size="sm">
            <Link to="/work-inbox">
              <Inbox data-icon="inline-start" />
              Bandeja
            </Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricTile title="Procesados" value={isLoading ? "-" : snapshot.processedDocuments} meta="Documentos completados" tone="success" icon={<CheckCircle2 className="h-4 w-4" />} />
        <MetricTile title="Pendientes" value={snapshot.pendingDocuments} meta={`${snapshot.pendingJobs} jobs activos`} tone={snapshot.pendingDocuments ? "warning" : "neutral"} icon={<Clock className="h-4 w-4" />} />
        <MetricTile title="Revisión" value={snapshot.reviewDocuments} meta={`${snapshot.lowOcrPages} páginas OCR bajo`} tone={snapshot.reviewDocuments ? "warning" : "neutral"} icon={<FileWarning className="h-4 w-4" />} />
        <MetricTile title="Incidencias" value={snapshot.criticalAlerts} meta={`${snapshot.openWorkItems} items en bandeja`} tone={snapshot.criticalAlerts ? "danger" : "success"} icon={<AlertTriangle className="h-4 w-4" />} />
        <MetricTile title="ETA cola" value={snapshot.etaLabel} meta={snapshot.backpressureActive ? "Backpressure activo" : "Cola estable"} tone={snapshot.backpressureActive ? "warning" : "neutral"} icon={<Activity className="h-4 w-4" />} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <Card>
            <CardHeader className="flex-row items-center justify-between gap-3">
              <CardTitle>Trabajo prioritario</CardTitle>
              <Button asChild variant="outline" size="sm">
                <Link to="/work-inbox">
                  Abrir bandeja
                  <ArrowRight data-icon="inline-start" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent className="space-y-2">
              {topInbox.map((item, index) => (
                <Link
                  key={`${item.kind}-${item.document_id ?? "d"}-${item.job_id ?? "j"}-${item.page_id ?? "p"}-${index}`}
                  to={workInboxTarget(item)}
                  className="flex items-center justify-between gap-3 rounded-md border bg-white p-3 text-sm transition-colors hover:bg-slate-50"
                >
                  <div className="min-w-0">
                    <div className="mb-1 flex items-center gap-2">
                      <Badge variant={toneToBadge(severityTone(item.severity))}>{item.kind}</Badge>
                      <span className="text-xs text-muted-foreground">{item.status ?? "pendiente"}</span>
                    </div>
                    <p className="truncate font-medium">{item.title}</p>
                    <p className="truncate text-xs text-muted-foreground">{item.description}</p>
                  </div>
                  <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                </Link>
              ))}
              {!topInbox.length ? <EmptyState title="Sin trabajo pendiente" description="No hay incidencias activas en la bandeja operativa." /> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center justify-between gap-3">
              <CardTitle>Distribución documental</CardTitle>
              <Button asChild variant="outline" size="sm">
                <Link to="/documents">
                  Ver tabla
                  <ArrowRight data-icon="inline-start" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-3">
              <Distribution title="Estados" values={metrics.data?.documents_by_status} />
              <Distribution title="Tipos" values={metrics.data?.documents_by_type} />
              <Distribution title="Jobs" values={metrics.data?.jobs_by_status} />
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <ActionPanel title="Acciones rápidas">
            <Button asChild className="w-full justify-start" variant="outline">
              <Link to="/documents">
                <RefreshCw data-icon="inline-start" />
                Escanear o subir documentos
              </Link>
            </Button>
            <Button asChild className="w-full justify-start" variant="outline">
              <Link to="/ocr-review">
                <FileWarning data-icon="inline-start" />
                Revisar OCR pendiente
              </Link>
            </Button>
            <Button asChild className="w-full justify-start" variant="outline">
              <Link to="/admin">
                <Activity data-icon="inline-start" />
                Ver readiness productivo
              </Link>
            </Button>
          </ActionPanel>

          <Card>
            <CardHeader>
              <CardTitle>Alertas operativas</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {topAlerts.map((alert) => (
                <div key={alert.key} className="rounded-md border p-3 text-sm">
                  <div className="mb-2 flex items-center justify-between gap-2">
                    <Badge variant={toneToBadge(severityTone(alert.severity))}>{alert.severity}</Badge>
                    <Button asChild variant="outline" size="sm">
                      <Link to={alert.action_url}>{alert.count}</Link>
                    </Button>
                  </div>
                  <p className="font-medium">{alert.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{alert.description}</p>
                </div>
              ))}
              {!topAlerts.length ? <p className="text-sm text-muted-foreground">Sin alertas activas.</p> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Resumen</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Line label="Total documentos" value={data?.documents_total ?? "-"} />
              <Line label="Duplicados" value={data?.duplicates ?? "-"} />
              <Line label="Fallidos" value={data?.documents_failed ?? "-"} />
              <Line label="Eventos auditados" value={metrics.data?.audit_events_total ?? "-"} />
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}

function Distribution({ title, values }: { title: string; values?: Record<string, number> }) {
  const entries = Object.entries(values ?? {}).slice(0, 7)
  return (
    <div className="rounded-md border bg-slate-50 p-3">
      <p className="mb-3 text-xs font-semibold uppercase tracking-normal text-muted-foreground">{title}</p>
      <div className="space-y-2">
        {entries.map(([status, count]) => (
          <div key={status} className="flex items-center justify-between gap-2 text-sm">
            <div className="flex min-w-0 items-center gap-2">
              <StatusBadge status={status} />
              <span className="truncate text-muted-foreground">{status}</span>
            </div>
            <span className="font-semibold">{count}</span>
          </div>
        ))}
        {!entries.length ? <p className="text-sm text-muted-foreground">Sin datos.</p> : null}
      </div>
    </div>
  )
}

function Line({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-semibold">{value}</span>
    </div>
  )
}

function toneToBadge(tone: ReturnType<typeof severityTone>): BadgeProps["variant"] {
  if (tone === "danger") return "danger"
  if (tone === "warning") return "warning"
  if (tone === "info") return "info"
  if (tone === "success") return "success"
  return "neutral"
}
