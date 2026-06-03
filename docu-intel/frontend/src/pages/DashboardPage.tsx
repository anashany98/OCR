import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Database,
  FileWarning,
  HardDrive,
  Inbox,
  RefreshCw,
  Search,
  Server,
  ShieldAlert,
  Workflow,
} from "lucide-react"

import { api } from "@/api/client"
import { ActionPanel } from "@/components/layout/ActionPanel"
import { MetricTile } from "@/components/layout/MetricTile"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { formatEta } from "@/lib/operations"
import type { AdminAlert, SystemHealth, OperationsOverview, QueueStatus, AdminStats } from "@/types/api"

// ---------------------------------------------------------------------------
// Urgent action definition
// ---------------------------------------------------------------------------
type UrgentAction = {
  label: string
  description: string
  to: string
  icon: React.ComponentType<{ className?: string }>
  count?: number
  tone: "danger" | "warning" | "info"
}

export function DashboardPage() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats })
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts })
  const metrics = useQuery({ queryKey: ["processing-metrics"], queryFn: api.processingMetrics })
  const inbox = useQuery({ queryKey: ["work-inbox"], queryFn: () => api.workInbox({ limit: 50 }), refetchInterval: 15000 })
  const overview = useQuery({ queryKey: ["operations-overview"], queryFn: api.operationsOverview, refetchInterval: 15000 })
  const systemHealth = useQuery({ queryKey: ["system-health"], queryFn: api.systemHealth, refetchInterval: 30000 })

  const isLoading = stats.isLoading
  const d = stats.data
  const ov = overview.data
  const sh = systemHealth.data
  const inboxItems = inbox.data ?? []
  const alertItems = alerts.data ?? []

  // Urgent actions derived from live data
  const urgentActions = buildUrgentActions(d, inboxItems)

  return (
    <div className="space-y-6">
      {/* ================================================================ */}
      {/* ACCIONES URGENTES                                                */}
      {/* ================================================================ */}
      {urgentActions.length > 0 && (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-[var(--rose)]" />
            <h2 className="text-[14px] font-semibold text-[var(--text-primary)]">Acciones urgentes</h2>
            <Badge variant="danger" className="text-[10px]">{urgentActions.length}</Badge>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {urgentActions.map((action) => (
              <Link
                key={action.to + action.label}
                to={action.to}
                className={cn(
                  "group flex items-start gap-3 rounded-xl border p-4 transition-all duration-150 hover:-translate-y-0.5 hover:shadow-md",
                  action.tone === "danger" && "border-[var(--rose-light)] bg-[var(--rose-light)]/30 hover:border-[var(--rose)]",
                  action.tone === "warning" && "border-[var(--amber-light)] bg-[var(--amber-light)]/30 hover:border-[var(--amber)]",
                  action.tone === "info" && "border-[var(--sky-light)] bg-[var(--sky-light)]/30 hover:border-[var(--sky)]",
                )}
              >
                <action.icon className={cn(
                  "mt-0.5 h-5 w-5 flex-shrink-0",
                  action.tone === "danger" && "text-[var(--rose)]",
                  action.tone === "warning" && "text-[var(--amber)]",
                  action.tone === "info" && "text-[var(--sky)]",
                )} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="text-[13px] font-semibold text-[var(--text-primary)]">{action.label}</p>
                    {action.count != null && action.count > 0 && (
                      <span className={cn(
                        "flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[11px] font-bold",
                        action.tone === "danger" && "bg-[var(--rose)] text-white",
                        action.tone === "warning" && "bg-[var(--amber)] text-white",
                        action.tone === "info" && "bg-[var(--sky)] text-white",
                      )}>
                        {action.count > 99 ? "99+" : action.count}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">{action.description}</p>
                </div>
                <ArrowRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-[var(--text-muted)] opacity-0 transition-all group-hover:opacity-100 group-hover:translate-x-0.5" />
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* ================================================================ */}
      {/* MÉTRICAS OPERATIVAS                                              */}
      {/* ================================================================ */}
      <section>
        <h2 className="mb-3 text-[14px] font-semibold text-[var(--text-primary)]">Visión operativa</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
          <MetricTile
            title="Procesados hoy"
            value={isLoading ? "—" : d?.documents_processed ?? 0}
            meta={`${d?.documents_total ?? 0} totales`}
            tone="success"
            icon={<CheckCircle2 className="h-4 w-4" />}
          />
          <MetricTile
            title="Pendientes"
            value={isLoading ? "—" : d?.documents_pending ?? 0}
            meta={ov?.jobs.pending_or_processing ? `${ov.jobs.pending_or_processing} en cola` : "Sin atascos"}
            tone={d?.documents_pending ? "warning" : "neutral"}
            icon={<Clock className="h-4 w-4" />}
          />
          <MetricTile
            title="Fallidos"
            value={isLoading ? "—" : d?.documents_failed ?? 0}
            meta="Requieren atención"
            tone={d?.documents_failed ? "danger" : "success"}
            icon={<AlertTriangle className="h-4 w-4" />}
          />
          <MetricTile
            title="En revisión"
            value={isLoading ? "—" : d?.documents_needs_review ?? 0}
            meta={ov?.documents.low_ocr_pages ? `${ov.documents.low_ocr_pages} pág. OCR bajo` : "Sin revisión"}
            tone={d?.documents_needs_review ? "warning" : "neutral"}
            icon={<FileWarning className="h-4 w-4" />}
          />
          <MetricTile
            title="Cola OCR"
            value={ov?.jobs.pending_or_processing ?? "—"}
            meta={`ETA ${formatEta(ov?.jobs.estimated_remaining_seconds)}`}
            tone={ov?.jobs.pending_or_processing ? "info" : "neutral"}
            icon={<Workflow className="h-4 w-4" />}
          />
          <MetricTile
            title="Tareas activas"
            value={inboxItems.length}
            meta={inboxItems.filter((i) => i.severity === "error" || i.severity === "critical").length > 0 ? `${inboxItems.filter((i) => i.severity === "error" || i.severity === "critical").length} críticas` : "Sin críticas"}
            tone={inboxItems.filter((i) => i.severity === "error" || i.severity === "critical").length > 0 ? "danger" : "success"}
            icon={<Inbox className="h-4 w-4" />}
          />
        </div>
      </section>

      {/* ================================================================ */}
      {/* GRID PRINCIPAL                                                   */}
      {/* ================================================================ */}
      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        {/* Left column */}
        <div className="space-y-4">
          {/* Quality & control metrics */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MiniMetric
              label="OCR bajo"
              value={ov?.documents.low_ocr_pages ?? 0}
              icon={FileWarning}
              tone="warning"
              to="/ocr-review"
            />
            <MiniMetric
              label="Duplicados"
              value={d?.duplicates ?? 0}
              icon={FileWarning}
              tone="info"
              to="/admin?tab=calidad"
            />
            <MiniMetric
              label="Cuarentena"
              value={0}
              icon={ShieldAlert}
              tone="danger"
              to="/admin?tab=calidad"
            />
            <MiniMetric
              label="Ppto. sin pedido"
              value={d?.accepted_budgets_without_order ?? 0}
              icon={AlertTriangle}
              tone="warning"
              to="/budgets"
            />
          </div>

          {/* Work priority */}
          <Card className="overflow-hidden">
            <CardHeader className="flex-row items-center justify-between pb-3">
              <div>
                <CardTitle className="text-[14px] font-semibold">Trabajo prioritario</CardTitle>
                <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">
                  {inboxItems.length > 0 ? `${inboxItems.length} incidencias requieren atención` : "Sin incidencias pendientes"}
                </p>
              </div>
              <Button asChild variant="outline" size="sm">
                <Link to="/work-inbox" className="text-[12px]">
                  Ver todas las tareas
                  <ArrowRight className="ml-1 h-3 w-3" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent className="space-y-2 px-5 pb-5">
              {inboxItems.slice(0, 6).map((item, index) => (
                <Link
                  key={`${item.kind}-${item.document_id ?? "d"}-${index}`}
                  to={item.action_url || `/work-inbox`}
                  className="group flex items-center justify-between gap-4 rounded-lg border border-[var(--border)] bg-white p-3 transition-all duration-150 hover:border-[var(--border-2)] hover:shadow-sm"
                >
                  <div className="flex items-start gap-3 min-w-0">
                    <span className={cn("mt-0.5 h-2 w-2 rounded-full flex-shrink-0",
                      item.severity === "error" || item.severity === "critical" ? "bg-[var(--rose)]" :
                      item.severity === "warning" ? "bg-[var(--amber)]" : "bg-[var(--sky)]"
                    )} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                          item.severity === "error" ? "bg-[var(--rose-light)] text-[#9F1239]" :
                          item.severity === "warning" ? "bg-[var(--amber-light)] text-[#92400E]" :
                          "bg-[var(--sky-light)] text-[#075985]"
                        )}>
                          {item.kind.replace(/_/g, " ")}
                        </span>
                      </div>
                      <p className="truncate text-[13px] font-medium text-[var(--text-primary)]">{item.title}</p>
                      <p className="truncate text-[12px] text-[var(--text-muted)]">{item.description}</p>
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 flex-shrink-0 text-[var(--text-muted)] transition-transform duration-150 group-hover:translate-x-0.5" />
                </Link>
              ))}
              {!inboxItems.length && (
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <CheckCircle2 className="h-8 w-8 text-[var(--emerald)] mb-2" />
                  <p className="text-[13px] font-medium text-[var(--text-secondary)]">Sin trabajo pendiente</p>
                  <p className="text-[12px] text-[var(--text-muted)] mt-1">No hay incidencias activas que requieran atención.</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Processing distribution */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px] font-semibold">Distribución documental</CardTitle>
            </CardHeader>
            <CardContent className="px-5 pb-5">
              <div className="grid gap-3 sm:grid-cols-3">
                <Distribution title="Por estado" values={metrics.data?.documents_by_status} />
                <Distribution title="Por tipo" values={metrics.data?.documents_by_type} />
                <Distribution title="Jobs" values={metrics.data?.jobs_by_status} />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Right column */}
        <div className="space-y-4">
          {/* Infrastructure status */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px] font-semibold flex items-center gap-2">
                <Server className="h-4 w-4 text-[var(--text-muted)]" />
                Infraestructura
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 px-5 pb-5">
              <InfraRow
                label="PostgreSQL"
                status={getCheckStatus(sh, "database")}
              />
              <InfraRow
                label="Redis"
                status={getCheckStatus(sh, "redis")}
              />
              <InfraRow
                label="Workers"
                status={getCheckStatus(sh, "celery")}
              />
              <InfraRow
                label="Watcher"
                status={getCheckStatus(sh, "watcher")}
              />
              <InfraRow
                label="Disco entrada"
                status={getDiskStatus(ov, "input")}
                detail={formatDiskSpace(ov?.disk?.input_dir)}
              />
              <InfraRow
                label="Disco archivos"
                status={getDiskStatus(ov, "files")}
                detail={formatDiskSpace(ov?.disk?.files_dir)}
              />
            </CardContent>
          </Card>

          {/* Alerts */}
          <Card>
            <CardHeader className="flex-row items-center justify-between pb-3">
              <CardTitle className="text-[14px] font-semibold flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-[var(--amber)]" />
                Alertas operativas
              </CardTitle>
              <Badge variant="warning">{alertItems.length}</Badge>
            </CardHeader>
            <CardContent className="space-y-2 px-5 pb-5">
              {alertItems.slice(0, 4).map((alert) => (
                <div key={alert.key} className="flex items-start justify-between gap-3 rounded-lg border border-[var(--border)] bg-white p-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={cn("h-1.5 w-1.5 rounded-full flex-shrink-0",
                        alert.severity === "critical" ? "bg-[var(--rose)]" :
                        alert.severity === "warning" ? "bg-[var(--amber)]" : "bg-[var(--sky)]"
                      )} />
                      <p className="text-[13px] font-medium text-[var(--text-primary)]">{alert.title}</p>
                    </div>
                    <p className="mt-1 text-[11px] text-[var(--text-muted)] pl-4">{alert.description}</p>
                  </div>
                  <Badge variant={alert.severity === "critical" ? "danger" : alert.severity === "warning" ? "warning" : "info"} className="flex-shrink-0">
                    {alert.count}
                  </Badge>
                </div>
              ))}
              {!alertItems.length && (
                <p className="py-4 text-center text-[12px] text-[var(--text-muted)]">Sin alertas activas</p>
              )}
            </CardContent>
          </Card>

          {/* Quick actions */}
          <ActionPanel title="Acciones rápidas">
            <Button asChild variant="outline" size="sm" className="w-full justify-start">
              <Link to="/documents">
                <RefreshCw className="mr-2 h-4 w-4" />
                Escanear documentos
              </Link>
            </Button>
            <Button asChild variant="outline" size="sm" className="w-full justify-start">
              <Link to="/search">
                <Search className="mr-2 h-4 w-4" />
                Buscar documentos
              </Link>
            </Button>
            <Button asChild variant="outline" size="sm" className="w-full justify-start">
              <Link to="/admin">
                <Activity className="mr-2 h-4 w-4" />
                Panel de administración
              </Link>
            </Button>
          </ActionPanel>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mini metric card
// ---------------------------------------------------------------------------
function MiniMetric({
  label,
  value,
  icon: Icon,
  tone,
  to,
}: {
  label: string
  value: number
  icon: React.ComponentType<{ className?: string }>
  tone: "danger" | "warning" | "info" | "neutral"
  to: string
}) {
  const colorMap = {
    danger: { bg: "bg-[var(--rose-light)]", border: "border-[var(--rose-light)]", text: "text-[#9F1239]", icon: "text-[var(--rose)]" },
    warning: { bg: "bg-[var(--amber-light)]", border: "border-[var(--amber-light)]", text: "text-[#92400E]", icon: "text-[var(--amber)]" },
    info: { bg: "bg-[var(--sky-light)]", border: "border-[var(--sky-light)]", text: "text-[#075985]", icon: "text-[var(--sky)]" },
    neutral: { bg: "bg-white", border: "border-[var(--border)]", text: "text-[var(--text-primary)]", icon: "text-[var(--text-muted)]" },
  }
  const c = colorMap[tone]

  return (
    <Link
      to={to}
      className={cn("group flex items-center gap-3 rounded-lg border p-3 transition-all hover:shadow-sm", c.bg, c.border)}
    >
      <Icon className={cn("h-4 w-4 flex-shrink-0", c.icon)} />
      <div>
        <p className={cn("text-lg font-bold", c.text)}>{value}</p>
        <p className="text-[11px] text-[var(--text-muted)]">{label}</p>
      </div>
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Infrastructure row
// ---------------------------------------------------------------------------
function InfraRow({ label, status, detail }: { label: string; status: "ok" | "warning" | "error" | "unknown"; detail?: string }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-[var(--border)] bg-white px-3 py-2 text-sm">
      <div className="flex items-center gap-2">
        <span className={cn("h-1.5 w-1.5 rounded-full",
          status === "ok" ? "bg-[var(--emerald)]" :
          status === "warning" ? "bg-[var(--amber)]" :
          status === "error" ? "bg-[var(--rose)]" : "bg-[var(--text-muted)]"
        )} />
        <span className="text-[var(--text-secondary)]">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        {detail && <span className="text-xs text-[var(--text-muted)]">{detail}</span>}
        <Badge variant={
          status === "ok" ? "success" :
          status === "warning" ? "warning" :
          status === "error" ? "danger" : "neutral"
        } className="text-[10px]">
          {status === "ok" ? "OK" : status === "warning" ? "WARN" : status === "error" ? "FAIL" : "?"}
        </Badge>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Distribution widget
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function buildUrgentActions(stats?: AdminStats, inbox?: { kind: string; severity: string; document_id: number | null }[]): UrgentAction[] {
  const actions: UrgentAction[] = []

  const failed = inbox?.filter((i) => i.kind === "failed_job").length ?? 0
  if (failed > 0) {
    actions.push({ label: "Jobs fallidos", description: `${failed} jobs requieren atención inmediata`, to: "/work-inbox", icon: ShieldAlert, count: failed, tone: "danger" })
  }

  const needsReview = stats?.documents_needs_review ?? 0
  if (needsReview > 0) {
    actions.push({ label: "Documentos en revisión", description: `${needsReview} documentos pendientes de validación`, to: "/ocr-review", icon: FileWarning, count: needsReview, tone: "warning" })
  }

  const lowOcr = inbox?.filter((i) => i.kind === "low_ocr").length ?? 0
  if (lowOcr > 0) {
    actions.push({ label: "OCR de baja confianza", description: `${lowOcr} páginas con OCR dudoso`, to: "/ocr-review", icon: FileWarning, count: lowOcr, tone: "warning" })
  }

  const budgetsWo = stats?.accepted_budgets_without_order ?? 0
  if (budgetsWo > 0) {
    actions.push({ label: "Pptos. sin pedido", description: `${budgetsWo} presupuestos aceptados sin pedido asociado`, to: "/budgets", icon: AlertTriangle, count: budgetsWo, tone: "warning" })
  }

  const failedDocs = stats?.documents_failed ?? 0
  if (failedDocs > 0) {
    actions.push({ label: "Documentos fallidos", description: `${failedDocs} documentos con error de procesamiento`, to: "/documents?status=failed", icon: AlertTriangle, count: failedDocs, tone: "danger" })
  }

  return actions.slice(0, 4)
}

function getCheckStatus(sh: SystemHealth | undefined, key: string): "ok" | "warning" | "error" | "unknown" {
  const check = sh?.checks?.[key]
  if (!check) return "unknown"
  if (check.status === "ok" || check.status === "healthy") return "ok"
  if (check.status === "warning" || check.status === "degraded") return "warning"
  return "error"
}

function getDiskStatus(ov: OperationsOverview | undefined, dir: "input" | "files"): "ok" | "warning" | "error" | "unknown" {
  const disk = dir === "input" ? ov?.disk?.input_dir : ov?.disk?.files_dir
  if (!disk) return "unknown"
  const pctUsed = disk.used / disk.total
  if (pctUsed > 0.90) return "error"
  if (pctUsed > 0.75) return "warning"
  return "ok"
}

function formatDiskSpace(disk?: { total: number; used: number; free: number }): string | undefined {
  if (!disk) return undefined
  const gbUsed = (disk.used / (1024 ** 3)).toFixed(1)
  const gbTotal = (disk.total / (1024 ** 3)).toFixed(1)
  return `${gbUsed} / ${gbTotal} GB`
}
