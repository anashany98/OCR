import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  FileWarning,
  Inbox,
  ScanLine,
  Search,
  ShieldAlert,
  Workflow,
} from "lucide-react"

import { api } from "@/api/client"
import { ActionPanel } from "@/components/layout/ActionPanel"
import { MetricTile } from "@/components/layout/MetricTile"
import { OnboardingCallout } from "@/components/layout/OnboardingCallout"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useCountUp } from "@/hooks/useCountUp"
import { cn } from "@/lib/utils"
import { formatEta } from "@/lib/operations"
import type { AdminStats } from "@/types/api"

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

  const urgentActions = buildUrgentActions(d, inboxItems)
  const isFirstTime = !stats.isLoading && (d?.documents_total ?? 0) === 0

  return (
    <div className="space-y-8">
      {isFirstTime && <OnboardingCallout />}

      {/* Editorial header — date stamp + greeting */}
      <DashboardHero stats={d} isLoading={isLoading} />

      {/* Urgent actions */}
      {urgentActions.length > 0 && (
        <section>
          <div className="mb-3 flex items-baseline gap-3">
            <h2 className="font-display text-[15px] font-medium tracking-tight text-[var(--text-primary)]">
              Atención inmediata
            </h2>
            <span className="text-[12px] text-[var(--text-muted)]">
              {urgentActions.length} {urgentActions.length === 1 ? "asunto" : "asuntos"} requieren intervención
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {urgentActions.map((action) => (
              <UrgentActionCard key={action.to + action.label} action={action} />
            ))}
          </div>
        </section>
      )}

      {/* Metric strip — editorial layout */}
      <section>
        <h2 className="mb-3 font-display text-[15px] font-medium tracking-tight text-[var(--text-primary)]">
          Operación de hoy
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <MetricTile
            title="Procesados"
            value={isLoading ? "—" : d?.documents_processed ?? 0}
            meta={`${d?.documents_total ?? 0} totales`}
            tone="success"
            icon={<CheckCircle2 className="h-4 w-4" />}
          />
          <MetricTile
            title="En cola"
            value={ov?.jobs.pending_or_processing ?? "—"}
            meta={`${formatEta(ov?.jobs.estimated_remaining_seconds)} restantes`}
            tone={(ov?.jobs.pending_or_processing ?? 0) > 0 ? "warning" : "neutral"}
            icon={<Clock className="h-4 w-4" />}
          />
          <MetricTile
            title="Fallidos"
            value={isLoading ? "—" : d?.documents_failed ?? 0}
            meta="Requieren atención"
            tone={(d?.documents_failed ?? 0) > 0 ? "danger" : "success"}
            icon={<AlertTriangle className="h-4 w-4" />}
          />
          <MetricTile
            title="En revisión"
            value={isLoading ? "—" : d?.documents_needs_review ?? 0}
            meta={ov?.documents.low_ocr_pages ? `${ov.documents.low_ocr_pages} con OCR bajo` : "Sin cola"}
            tone={(d?.documents_needs_review ?? 0) > 0 ? "warning" : "neutral"}
            icon={<FileWarning className="h-4 w-4" />}
          />
          <MetricTile
            title="Pipeline"
            value={ov?.jobs.pending_or_processing ?? "—"}
            meta="Workers disponibles"
            tone="info"
            icon={<Workflow className="h-4 w-4" />}
          />
          <MetricTile
            title="Incidencias"
            value={inboxItems.length}
            meta={(() => {
              const critical = inboxItems.filter((i) => i.severity === "error" || i.severity === "critical").length
              return critical > 0 ? `${critical} críticas` : "Sin críticas"
            })()}
            tone={(() => {
              const critical = inboxItems.filter((i) => i.severity === "error" || i.severity === "critical").length
              return critical > 0 ? "danger" : "success"
            })()}
            icon={<Inbox className="h-4 w-4" />}
          />
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        {/* Left column */}
        <div className="space-y-6">
          <PriorityWorkCard inboxItems={inboxItems} />
          <DistributionCard metrics={metrics.data} />
        </div>

        {/* Right column */}
        <div className="space-y-6">
          <InfrastructureCard sh={sh} ov={ov} />
          <AlertsCard alertItems={alertItems} />
          <ActionPanel
            title="Atajos"
            description="Tres accesos rápidos para las tareas más habituales."
          >
            <Button asChild variant="ghost" size="sm" className="w-full justify-between text-[13px]">
              <Link to="/documents">
                <span className="flex items-center gap-2">
                  <ScanLine className="h-4 w-4 text-[var(--text-muted)]" /> Escanear documentos
                </span>
                <ArrowUpRight className="h-3.5 w-3.5 text-[var(--text-muted)]" />
              </Link>
            </Button>
            <Button asChild variant="ghost" size="sm" className="w-full justify-between text-[13px]">
              <Link to="/search">
                <span className="flex items-center gap-2">
                  <Search className="h-4 w-4 text-[var(--text-muted)]" /> Buscar documentos
                </span>
                <ArrowUpRight className="h-3.5 w-3.5 text-[var(--text-muted)]" />
              </Link>
            </Button>
            <Button asChild variant="ghost" size="sm" className="w-full justify-between text-[13px]">
              <Link to="/admin">
                <span className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-[var(--text-muted)]" /> Panel de operación
                </span>
                <ArrowUpRight className="h-3.5 w-3.5 text-[var(--text-muted)]" />
              </Link>
            </Button>
          </ActionPanel>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Hero — editorial date stamp with animated primary number
// ---------------------------------------------------------------------------
function DashboardHero({ stats, isLoading }: { stats: AdminStats | undefined; isLoading: boolean }) {
  const processedCount = useCountUp(isLoading ? 0 : stats?.documents_processed ?? 0, 900)
  const totalCount = useCountUp(isLoading ? 0 : stats?.documents_total ?? 0, 1100)
  const today = new Date().toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long", year: "numeric" })

  return (
    <header className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-6 shadow-paper md:p-8">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0 space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">{today}</p>
          <h1 className="font-display text-[28px] font-medium leading-[1.1] tracking-tight text-[var(--text-primary)] md:text-[34px]">
            {totalCount > 0 ? (
              <>
                <span className="tabular-nums">{totalCount.toLocaleString("es-ES")}</span> documentos bajo control
              </>
            ) : (
              "Tu centro de trabajo documental"
            )}
          </h1>
          <p className="max-w-xl text-[14px] text-[var(--text-secondary)] leading-relaxed">
            Vista general del procesamiento automático, la calidad de extracción y las tareas que necesitan tu atención.
          </p>
        </div>

        <div className="flex items-end gap-6">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--text-muted)]">Procesados hoy</p>
            <p className="font-display text-[44px] font-medium leading-none tracking-tight text-[var(--text-primary)] tabular-nums">
              {isLoading ? "—" : processedCount.toLocaleString("es-ES")}
            </p>
          </div>
        </div>
      </div>
    </header>
  )
}

// ---------------------------------------------------------------------------
// Urgent action — editorial tile
// ---------------------------------------------------------------------------
function UrgentActionCard({ action }: { action: UrgentAction }) {
  const Icon = action.icon
  const tone = action.tone
  const ring = tone === "danger" ? "border-[var(--danger)]/20 bg-[var(--danger-faint)]" : tone === "warning" ? "border-[var(--warning)]/20 bg-[var(--warning-faint)]" : "border-[var(--info)]/20 bg-[var(--info-faint)]"
  const accentText = tone === "danger" ? "text-[var(--text-on-danger)]" : tone === "warning" ? "text-[var(--text-on-warning)]" : "text-[var(--text-on-info)]"
  const accentIcon = tone === "danger" ? "text-[var(--danger)]" : tone === "warning" ? "text-[var(--warning)]" : "text-[var(--info)]"

  return (
    <Link
      to={action.to}
      className={cn(
        "group relative flex flex-col gap-2 rounded-xl border p-4 transition-all duration-base ease-out hover-lift",
        ring,
      )}
    >
      <div className="flex items-start justify-between">
        <Icon className={cn("h-4 w-4", accentIcon)} aria-hidden="true" />
        {action.count != null && action.count > 0 && (
          <span
            className={cn(
              "flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[10px] font-semibold text-white",
              tone === "danger" ? "bg-[var(--danger)]" : tone === "warning" ? "bg-[var(--warning)]" : "bg-[var(--info)]",
            )}
          >
            {action.count > 99 ? "99+" : action.count}
          </span>
        )}
      </div>
      <p className={cn("font-display text-[15px] font-medium leading-tight tracking-tight", accentText)}>{action.label}</p>
      <p className="text-[12px] text-[var(--text-muted)] leading-relaxed">{action.description}</p>
      <ArrowRight className="absolute bottom-3 right-3 h-3.5 w-3.5 text-[var(--text-muted)] opacity-0 transition-all group-hover:opacity-100 group-hover:translate-x-0.5" />
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Priority work card — editorial list
// ---------------------------------------------------------------------------
function PriorityWorkCard({ inboxItems }: { inboxItems: any[] }) {
  return (
    <Card>
      <CardHeader className="flex-row items-baseline justify-between border-b border-[var(--border)] pb-4">
        <div>
          <CardTitle>Trabajo prioritario</CardTitle>
          <p className="mt-1 text-[12px] text-[var(--text-muted)]">
            {inboxItems.length > 0
              ? `${inboxItems.length} ${inboxItems.length === 1 ? "incidencia" : "incidencias"} abiertas`
              : "Bandeja vacía"}
          </p>
        </div>
        <Button asChild variant="ghost" size="sm" className="text-[12px] text-[var(--accent)] hover:text-[var(--accent-hover)]">
          <Link to="/work-inbox">
            Ver todas <ArrowRight className="ml-1 h-3 w-3" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="px-0 py-0">
        {inboxItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--positive-faint)] text-[var(--positive)]">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <div className="space-y-1">
              <p className="font-display text-[15px] font-medium text-[var(--text-primary)]">Sin trabajo pendiente</p>
              <p className="text-[12px] text-[var(--text-muted)]">No hay incidencias activas. Buen trabajo.</p>
            </div>
          </div>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {inboxItems.slice(0, 6).map((item, index) => (
              <li key={`${item.kind}-${item.document_id ?? "d"}-${index}`}>
                <Link
                  to={item.action_url || "/work-inbox"}
                  className="group flex items-start gap-3 px-6 py-3.5 transition-colors duration-fast ease-out hover:bg-[var(--bg-surface-2)]/60"
                >
                  <span
                    className={cn(
                      "mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full",
                      item.severity === "error" || item.severity === "critical"
                        ? "bg-[var(--danger)]"
                        : item.severity === "warning"
                          ? "bg-[var(--warning)]"
                          : "bg-[var(--info)]",
                    )}
                  />
                  <div className="min-w-0 flex-1 space-y-0.5">
                    <p className="truncate text-[13px] font-medium text-[var(--text-primary)]">{item.title}</p>
                    <p className="truncate text-[12px] text-[var(--text-muted)]">{item.description}</p>
                  </div>
                  <ArrowRight className="mt-2 h-3.5 w-3.5 flex-shrink-0 text-[var(--text-muted)] opacity-0 transition-all group-hover:opacity-100 group-hover:translate-x-0.5" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Distribution card
// ---------------------------------------------------------------------------
function DistributionCard({ metrics }: { metrics: any }) {
  return (
    <Card>
      <CardHeader className="border-b border-[var(--border)] pb-4">
        <CardTitle>Distribución</CardTitle>
        <p className="mt-1 text-[12px] text-[var(--text-muted)]">Cómo se reparten los documentos y los jobs en curso.</p>
      </CardHeader>
      <CardContent>
        <div className="grid gap-6 sm:grid-cols-3">
          <DistributionColumn title="Por estado" values={metrics?.documents_by_status} />
          <DistributionColumn title="Por tipo" values={metrics?.documents_by_type} />
          <DistributionColumn title="Jobs" values={metrics?.jobs_by_status} />
        </div>
      </CardContent>
    </Card>
  )
}

function DistributionColumn({ title, values }: { title: string; values?: Record<string, number> }) {
  const entries = Object.entries(values ?? {}).slice(0, 7)
  const total = entries.reduce((sum, [, n]) => sum + n, 0)
  return (
    <div className="space-y-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--text-muted)]">{title}</p>
      <div className="space-y-2">
        {entries.map(([key, count]) => {
          const pct = total > 0 ? (count / total) * 100 : 0
          return (
            <div key={key} className="space-y-1">
              <div className="flex items-center justify-between text-[12px]">
                <span className="truncate text-[var(--text-secondary)] capitalize">{key.replace(/_/g, " ")}</span>
                <span className="font-mono text-[11px] text-[var(--text-muted)] tabular-nums">{count}</span>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-[var(--bg-surface-2)]">
                <div
                  className="h-full rounded-full bg-[var(--accent)] transition-all duration-slow ease-out"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          )
        })}
        {entries.length === 0 && <p className="text-[12px] text-[var(--text-muted)]">Sin datos</p>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Infrastructure card
// ---------------------------------------------------------------------------
function InfrastructureCard({ sh, ov }: { sh: any; ov: any }) {
  return (
    <Card>
      <CardHeader className="border-b border-[var(--border)] pb-4">
        <CardTitle className="text-[14px]">Infraestructura</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <InfraRow label="PostgreSQL" status={getCheckStatus(sh, "database")} />
        <InfraRow label="Redis" status={getCheckStatus(sh, "redis")} />
        <InfraRow label="Workers" status={getCheckStatus(sh, "celery")} />
        <InfraRow label="Watcher" status={getCheckStatus(sh, "watcher")} />
        <InfraRow label="Disco entrada" status={getDiskStatus(ov, "input")} detail={formatDiskSpace(ov?.disk?.input_dir)} />
        <InfraRow label="Disco archivos" status={getDiskStatus(ov, "files")} detail={formatDiskSpace(ov?.disk?.files_dir)} />
      </CardContent>
    </Card>
  )
}

function InfraRow({ label, status, detail }: { label: string; status: "ok" | "warning" | "error" | "unknown"; detail?: string }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-[var(--border)] bg-transparent px-3 py-2 text-[13px]">
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            status === "ok" ? "bg-[var(--positive)]" : status === "warning" ? "bg-[var(--warning)]" : status === "error" ? "bg-[var(--danger)]" : "bg-[var(--text-muted)]",
          )}
        />
        <span className="text-[var(--text-secondary)]">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        {detail && <span className="font-mono text-[11px] text-[var(--text-muted)] tabular-nums">{detail}</span>}
        <Badge
          variant={
            status === "ok" ? "success" : status === "warning" ? "warning" : status === "error" ? "danger" : "neutral"
          }
          className="text-[10px]"
        >
          {status === "ok" ? "OK" : status === "warning" ? "WARN" : status === "error" ? "FAIL" : "—"}
        </Badge>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Alerts card
// ---------------------------------------------------------------------------
function AlertsCard({ alertItems }: { alertItems: any[] }) {
  return (
    <Card>
      <CardHeader className="flex-row items-baseline justify-between border-b border-[var(--border)] pb-4">
        <CardTitle className="text-[14px]">Alertas</CardTitle>
        <Badge variant="warning">{alertItems.length}</Badge>
      </CardHeader>
      <CardContent className="px-0 py-0">
        {alertItems.length === 0 ? (
          <p className="py-6 text-center text-[12px] text-[var(--text-muted)]">Sin alertas activas</p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {alertItems.slice(0, 4).map((alert) => (
              <li key={alert.key} className="flex items-start justify-between gap-3 px-6 py-3">
                <div className="min-w-0 space-y-0.5">
                  <p className="text-[13px] font-medium text-[var(--text-primary)]">{alert.title}</p>
                  <p className="text-[11px] text-[var(--text-muted)] leading-relaxed">{alert.description}</p>
                </div>
                <Badge
                  variant={alert.severity === "critical" ? "danger" : alert.severity === "warning" ? "warning" : "info"}
                  className="flex-shrink-0"
                >
                  {alert.count}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function buildUrgentActions(
  stats?: AdminStats,
  inbox?: { kind: string; severity: string; document_id: number | null }[],
): UrgentAction[] {
  const actions: UrgentAction[] = []
  const failed = inbox?.filter((i) => i.kind === "failed_job").length ?? 0
  if (failed > 0) actions.push({ label: "Jobs fallidos", description: `${failed} jobs requieren atención inmediata`, to: "/work-inbox", icon: ShieldAlert, count: failed, tone: "danger" })
  const needsReview = stats?.documents_needs_review ?? 0
  if (needsReview > 0) actions.push({ label: "Documentos en revisión", description: `${needsReview} documentos pendientes de validación`, to: "/ocr-review", icon: FileWarning, count: needsReview, tone: "warning" })
  const lowOcr = inbox?.filter((i) => i.kind === "low_ocr").length ?? 0
  if (lowOcr > 0) actions.push({ label: "OCR de baja confianza", description: `${lowOcr} páginas con OCR dudoso`, to: "/ocr-review", icon: FileWarning, count: lowOcr, tone: "warning" })
  const budgetsWo = stats?.accepted_budgets_without_order ?? 0
  if (budgetsWo > 0) actions.push({ label: "Pptos. sin pedido", description: `${budgetsWo} presupuestos aceptados sin pedido asociado`, to: "/budgets", icon: AlertTriangle, count: budgetsWo, tone: "warning" })
  return actions.slice(0, 4)
}

function getCheckStatus(sh: any, key: string): "ok" | "warning" | "error" | "unknown" {
  const check = sh?.checks?.[key]
  if (!check) return "unknown"
  if (check.status === "ok" || check.status === "healthy") return "ok"
  if (check.status === "warning" || check.status === "degraded") return "warning"
  return "error"
}

function getDiskStatus(ov: any, dir: "input" | "files"): "ok" | "warning" | "error" | "unknown" {
  const disk = dir === "input" ? ov?.disk?.input_dir : ov?.disk?.files_dir
  if (!disk) return "unknown"
  const pctUsed = disk.used / disk.total
  if (pctUsed > 0.9) return "error"
  if (pctUsed > 0.75) return "warning"
  return "ok"
}

function formatDiskSpace(disk?: { total: number; used: number; free: number }): string | undefined {
  if (!disk) return undefined
  const gbUsed = (disk.used / 1024 ** 3).toFixed(1)
  const gbTotal = (disk.total / 1024 ** 3).toFixed(1)
  return `${gbUsed} / ${gbTotal} GB`
}
