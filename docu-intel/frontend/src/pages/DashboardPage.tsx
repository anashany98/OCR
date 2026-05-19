import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { Activity, AlertTriangle, ArrowRight, CheckCircle2, Clock, FileWarning, Inbox, RefreshCw } from "lucide-react"

import { api } from "@/api/client"
import { ActionPanel } from "@/components/layout/ActionPanel"
import { MetricTile } from "@/components/layout/MetricTile"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { buildTodaySnapshot } from "@/lib/operations"
import { severityTone } from "@/lib/status"

const alertVariant: Record<string, "success" | "info" | "warning" | "danger" | "neutral"> = {
  error: "danger",
  warning: "warning",
  info: "info",
  critical: "danger",
}

export function DashboardPage() {
  const { data, isLoading } = useQuery({ queryKey: ["stats"], queryFn: api.stats })
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts })
  const metrics = useQuery({ queryKey: ["processing-metrics"], queryFn: api.processingMetrics })
  const inbox = useQuery({ queryKey: ["work-inbox"], queryFn: () => api.workInbox({ limit: 8 }), refetchInterval: 15000 })
  const overview = useQuery({ queryKey: ["operations-overview"], queryFn: api.operationsOverview, refetchInterval: 15000 })
  const snapshot = buildTodaySnapshot({ stats: data, alerts: alerts.data, inbox: inbox.data, overview: overview.data })
  const topInbox = (inbox.data ?? []).slice(0, 6)

  return (
    <div className="space-y-6">
      {/* Metric cards row */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricTile
          title="Procesados"
          value={isLoading ? "—" : snapshot.processedDocuments}
          meta={`${data?.documents_processed ?? 0} completados`}
          tone="success"
          icon={<CheckCircle2 className="h-4 w-4" />}
          className="animate-fade-in-up"
        />
        <MetricTile
          title="Pendientes"
          value={snapshot.pendingDocuments}
          meta={snapshot.pendingJobs ? `${snapshot.pendingJobs} jobs activos` : "Sin jobs activos"}
          tone={snapshot.pendingDocuments ? "warning" : "neutral"}
          icon={<Clock className="h-4 w-4" />}
          className="animate-fade-in-up delay-50"
        />
        <MetricTile
          title="Revisión"
          value={snapshot.reviewDocuments}
          meta={snapshot.lowOcrPages ? `${snapshot.lowOcrPages} pág. OCR bajo` : "Sin revisión pendiente"}
          tone={snapshot.reviewDocuments ? "warning" : "neutral"}
          icon={<FileWarning className="h-4 w-4" />}
          className="animate-fade-in-up delay-100"
        />
        <MetricTile
          title="Incidencias"
          value={snapshot.criticalAlerts}
          meta={snapshot.openWorkItems ? `${snapshot.openWorkItems} items en bandeja` : "Sin incidencias"}
          tone={snapshot.criticalAlerts ? "danger" : "success"}
          icon={<AlertTriangle className="h-4 w-4" />}
          className="animate-fade-in-up delay-150"
        />
        <MetricTile
          title="ETA Cola"
          value={snapshot.etaLabel}
          meta={snapshot.backpressureActive ? "Backpressure activo" : "Cola estable"}
          tone={snapshot.backpressureActive ? "warning" : "neutral"}
          icon={<Activity className="h-4 w-4" />}
          className="animate-fade-in-up delay-200"
        />
      </div>

      {/* Main content grid */}
      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        {/* Left column */}
        <div className="space-y-4">
          {/* Work priority */}
          <Card className="overflow-hidden">
            <CardHeader className="flex-row items-center justify-between pb-3">
              <div>
                <CardTitle className="text-[14px] font-semibold">Trabajo prioritario</CardTitle>
                <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">
                  {topInbox.length > 0 ? `${topInbox.length} items requieren atención` : "Sin incidencias pendientes"}
                </p>
              </div>
              <Button asChild variant="outline" size="sm">
                <Link to="/work-inbox" className="text-[12px]">
                  Ver bandeja
                  <ArrowRight className="h-3 w-3" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent className="space-y-2 px-5 pb-5">
              {topInbox.map((item, index) => (
                <Link
                  key={`${item.kind}-${item.document_id ?? "d"}-${item.job_id ?? "j"}-${index}`}
                  to={item.action_url || "#"}
                  className="group flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-white p-4 transition-all duration-150 hover:border-[var(--border-2)] hover:shadow-sm"
                >
                  <div className="flex items-start gap-3 min-w-0">
                    <span
                      className={`mt-0.5 h-2 w-2 rounded-full flex-shrink-0 ${
                        item.severity === "error" || item.severity === "critical" ? "bg-[var(--rose)]" :
                        item.severity === "warning" ? "bg-[var(--amber)]" : "bg-[var(--sky)]"
                      }`}
                    />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                          item.severity === "error" ? "bg-[var(--rose-light)] text-[#9F1239]" :
                          item.severity === "warning" ? "bg-[var(--amber-light)] text-[#92400E]" :
                          "bg-[var(--sky-light)] text-[#075985]"
                        }`}>
                          {item.kind}
                        </span>
                        {item.status && (
                          <span className="text-[11px] text-[var(--text-muted)]">{item.status}</span>
                        )}
                      </div>
                      <p className="truncate text-[13px] font-medium text-[var(--text-primary)]">{item.title}</p>
                      <p className="truncate text-[12px] text-[var(--text-muted)]">{item.description}</p>
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 flex-shrink-0 text-[var(--text-muted)] transition-transform duration-150 group-hover:translate-x-0.5" />
                </Link>
              ))}
              {!topInbox.length && (
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <CheckCircle2 className="h-8 w-8 text-[var(--emerald)] mb-2" />
                  <p className="text-[13px] font-medium text-[var(--text-secondary)]">Sin trabajo pendiente</p>
                  <p className="text-[12px] text-[var(--text-muted)] mt-1">No hay incidencias activas en la bandeja.</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Distribution */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px] font-semibold">Distribución documental</CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-5">
              <div className="grid gap-3 sm:grid-cols-3">
                <Distribution title="Estados" values={metrics.data?.documents_by_status} />
                <Distribution title="Tipos" values={metrics.data?.documents_by_type} />
                <Distribution title="Jobs" values={metrics.data?.jobs_by_status} />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Right column */}
        <div className="space-y-4">
          <ActionPanel title="Acciones rápidas">
            <Button asChild variant="outline" className="w-full justify-start">
              <Link to="/documents">
                <RefreshCw className="h-4 w-4" data-icon="inline-start" />
                Escanear documentos
              </Link>
            </Button>
            <Button asChild variant="outline" className="w-full justify-start">
              <Link to="/ocr-review">
                <FileWarning className="h-4 w-4" data-icon="inline-start" />
                Revisar OCR pendiente
              </Link>
            </Button>
            <Button asChild variant="outline" className="w-full justify-start">
              <Link to="/admin">
                <Activity className="h-4 w-4" data-icon="inline-start" />
                Readiness productivo
              </Link>
            </Button>
          </ActionPanel>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px] font-semibold">Alertas operativas</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 px-5 pb-5">
              {(alerts.data ?? []).slice(0, 4).map((alert) => (
                <div key={alert.key} className="flex items-start justify-between gap-3 rounded-lg border border-[var(--border)] bg-white p-3">
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium text-[var(--text-primary)]">{alert.title}</p>
                    <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{alert.description}</p>
                  </div>
                  <Badge variant={alertVariant[alert.severity] ?? "neutral"} className="flex-shrink-0">
                    {alert.count}
                  </Badge>
                </div>
              ))}
              {!(alerts.data ?? []).length && (
                <p className="py-4 text-center text-[12px] text-[var(--text-muted)]">Sin alertas activas</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px] font-semibold">Resumen</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1 px-5 pb-5">
              {[
                ["Total documentos", data?.documents_total ?? "—"],
                ["Duplicados", data?.duplicates ?? "—"],
                ["Fallidos", data?.documents_failed ?? "—"],
                ["Sin clasificar", data?.accepted_budgets_without_order ?? "—"],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between py-2 border-b border-[var(--border)] last:border-0">
                  <span className="text-[13px] text-[var(--text-secondary)]">{label}</span>
                  <span className="text-[13px] font-semibold text-[var(--text-primary)]">{value}</span>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function Distribution({ title, values }: { title: string; values?: Record<string, number> }) {
  const entries = Object.entries(values ?? {}).slice(0, 7)
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-3">{title}</p>
      <div className="space-y-2">
        {entries.map(([status, count]) => (
          <div key={status} className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <span className="status-dot bg-[var(--primary)]" />
              <span className="truncate text-[12px] text-[var(--text-secondary)] capitalize">{status.replace(/_/g, " ")}</span>
            </div>
            <span className="text-[12px] font-semibold text-[var(--text-primary)] shrink-0">{count}</span>
          </div>
        ))}
        {entries.length === 0 && (
          <p className="text-[12px] text-[var(--text-muted)]">Sin datos</p>
        )}
      </div>
    </div>
  )
}