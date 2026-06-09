import { type ReactNode } from "react"
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
  type LucideIcon,
} from "lucide-react"

import { ActionPanel } from "@/components/layout/ActionPanel"
import { MetricTile } from "@/components/layout/MetricTile"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useCountUp } from "@/hooks/useCountUp"
import { cn } from "@/lib/utils"
import { formatEta } from "@/lib/operations"
import type { AdminStats } from "@/types/api"

import {
  formatDiskSpace,
  getCheckStatus,
  getDiskStatus,
  type InfraStatus,
  type UrgentAction,
} from "./useDashboard"

// ---------------------------------------------------------------------------
// ICON_MAP
// ---------------------------------------------------------------------------
const ICON_MAP: Record<string, LucideIcon> = {
  ShieldAlert,
  FileWarning,
  AlertTriangle,
}

// ---------------------------------------------------------------------------
// DashboardHero — editorial date stamp with animated count
// ---------------------------------------------------------------------------
export function DashboardHero({
  stats,
  isLoading,
}: {
  stats: AdminStats | undefined
  isLoading: boolean
}) {
  const processedCount = useCountUp(isLoading ? 0 : stats?.documents_processed ?? 0, 900)
  const totalCount = useCountUp(isLoading ? 0 : stats?.documents_total ?? 0, 1100)
  const today = new Date().toLocaleDateString("es-ES", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  })
  return (
    <header className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-6 shadow-paper md:p-8">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0 space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">
            {today}
          </p>
          <h1 className="font-display text-[28px] font-medium leading-[1.1] tracking-tight text-[var(--text-primary)] md:text-[34px]">
            {totalCount > 0 ? (
              <>
                <span className="tabular-nums">{totalCount.toLocaleString("es-ES")}</span>{" "}
                documentos bajo control
              </>
            ) : (
              "Tu centro de trabajo documental"
            )}
          </h1>
          <p className="max-w-xl text-[14px] leading-relaxed text-[var(--text-secondary)]">
            Vista general del procesamiento automático, la calidad de extracción y las tareas
            que necesitan tu atención.
          </p>
        </div>
        <div className="flex items-end gap-6">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--text-muted)]">
              Procesados hoy
            </p>
            <p className="font-display text-[44px] font-medium leading-none tracking-tight tabular-nums text-[var(--text-primary)]">
              {isLoading ? "—" : processedCount.toLocaleString("es-ES")}
            </p>
          </div>
        </div>
      </div>
    </header>
  )
}

// ---------------------------------------------------------------------------
// UrgentActionCard
// ---------------------------------------------------------------------------
export function UrgentActionCard({ action }: { action: UrgentAction }) {
  const Icon = ICON_MAP[action.iconName] ?? ShieldAlert
  const tone = action.tone
  const ring =
    tone === "danger"
      ? "border-[var(--danger)]/20 bg-[var(--danger-faint)]"
      : tone === "warning"
        ? "border-[var(--warning)]/20 bg-[var(--warning-faint)]"
        : "border-[var(--info)]/20 bg-[var(--info-faint)]"
  const accentText =
    tone === "danger"
      ? "text-[var(--text-on-danger)]"
      : tone === "warning"
        ? "text-[var(--text-on-warning)]"
        : "text-[var(--text-on-info)]"
  const accentIcon =
    tone === "danger"
      ? "text-[var(--danger)]"
      : tone === "warning"
        ? "text-[var(--warning)]"
        : "text-[var(--info)]"
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
              tone === "danger"
                ? "bg-[var(--danger)]"
                : tone === "warning"
                  ? "bg-[var(--warning)]"
                  : "bg-[var(--info)]",
            )}
          >
            {action.count > 99 ? "99+" : action.count}
          </span>
        )}
      </div>
      <p
        className={cn(
          "font-display text-[15px] font-medium leading-tight tracking-tight",
          accentText,
        )}
      >
        {action.label}
      </p>
      <p className="text-[12px] leading-relaxed text-[var(--text-muted)]">{action.description}</p>
      <ArrowRight className="absolute bottom-3 right-3 h-3.5 w-3.5 text-[var(--text-muted)] opacity-0 transition-all group-hover:opacity-100 group-hover:translate-x-0.5" />
    </Link>
  )
}

// ---------------------------------------------------------------------------
// UrgentActionsSection
// ---------------------------------------------------------------------------
export function UrgentActionsSection({ actions }: { actions: UrgentAction[] }) {
  if (!actions.length) return null
  return (
    <section>
      <div className="mb-3 flex items-baseline gap-3">
        <h2 className="font-display text-[15px] font-medium tracking-tight text-[var(--text-primary)]">
          Atención inmediata
        </h2>
        <span className="text-[12px] text-[var(--text-muted)]">
          {actions.length} {actions.length === 1 ? "asunto" : "asuntos"} requieren intervención
        </span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {actions.map((action) => (
          <UrgentActionCard key={action.to + action.label} action={action} />
        ))}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// MetricStrip
// ---------------------------------------------------------------------------
export function MetricStrip({
  stats,
  isLoading,
  ov,
  inboxCount,
  criticalInboxCount,
}: {
  stats: AdminStats | undefined
  isLoading: boolean
  ov: { jobs: { pending_or_processing: number } } | undefined
  inboxCount: number
  criticalInboxCount: number
}) {
  return (
    <section>
      <h2 className="mb-3 font-display text-[15px] font-medium tracking-tight text-[var(--text-primary)]">
        Operación de hoy
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <MetricTile
          title="Procesados"
          value={isLoading ? "—" : stats?.documents_processed ?? 0}
          meta={`${stats?.documents_total ?? 0} totales`}
          tone="success"
          icon={<CheckCircle2 className="h-4 w-4" />}
        />
        <MetricTile
          title="En cola"
          value={ov?.jobs.pending_or_processing ?? "—"}
          meta={`${formatEta(undefined)} restantes`}
          tone={(ov?.jobs.pending_or_processing ?? 0) > 0 ? "warning" : "neutral"}
          icon={<Clock className="h-4 w-4" />}
        />
        <MetricTile
          title="Fallidos"
          value={isLoading ? "—" : stats?.documents_failed ?? 0}
          meta="Requieren atención"
          tone={(stats?.documents_failed ?? 0) > 0 ? "danger" : "success"}
          icon={<AlertTriangle className="h-4 w-4" />}
        />
        <MetricTile
          title="En revisión"
          value={isLoading ? "—" : stats?.documents_needs_review ?? 0}
          meta="Sin cola"
          tone={(stats?.documents_needs_review ?? 0) > 0 ? "warning" : "neutral"}
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
          value={inboxCount}
          meta={criticalInboxCount > 0 ? `${criticalInboxCount} críticas` : "Sin críticas"}
          tone={criticalInboxCount > 0 ? "danger" : "success"}
          icon={<Inbox className="h-4 w-4" />}
        />
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// PriorityWorkCard
// ---------------------------------------------------------------------------
type InboxItem = { kind: string; severity: string; title: string; description: string; action_url: string | null; document_id: number | null }
export function PriorityWorkCard({ inboxItems }: { inboxItems: InboxItem[] }) {
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
              <p className="font-display text-[15px] font-medium text-[var(--text-primary)]">
                Sin trabajo pendiente
              </p>
              <p className="text-[12px] text-[var(--text-muted)]">
                No hay incidencias activas. Buen trabajo.
              </p>
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
// DistributionCard + DistributionColumn
// ---------------------------------------------------------------------------
export function DistributionCard({
  metrics,
}: {
  metrics: {
    documents_by_status?: Record<string, number>
    documents_by_type?: Record<string, number>
    jobs_by_status?: Record<string, number>
  } | undefined
}) {
  return (
    <Card>
      <CardHeader className="border-b border-[var(--border)] pb-4">
        <CardTitle>Distribución</CardTitle>
        <p className="mt-1 text-[12px] text-[var(--text-muted)]">
          Cómo se reparten los documentos y los jobs en curso.
        </p>
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

function DistributionColumn({
  title,
  values,
}: {
  title: string
  values?: Record<string, number>
}) {
  const entries = Object.entries(values ?? {}).slice(0, 7)
  const total = entries.reduce((sum, [, n]) => sum + n, 0)
  return (
    <div className="space-y-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-[var(--text-muted)]">
        {title}
      </p>
      <div className="space-y-2">
        {entries.map(([key, count]) => {
          const pct = total > 0 ? (count / total) * 100 : 0
          return (
            <div key={key} className="space-y-1">
              <div className="flex items-center justify-between text-[12px]">
                <span className="truncate capitalize text-[var(--text-secondary)]">
                  {key.replace(/_/g, " ")}
                </span>
                <span className="font-mono text-[11px] tabular-nums text-[var(--text-muted)]">
                  {count}
                </span>
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
        {entries.length === 0 && (
          <p className="text-[12px] text-[var(--text-muted)]">Sin datos</p>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// InfrastructureCard + InfraRow
// ---------------------------------------------------------------------------
export function InfrastructureCard({
  sh,
  ov,
}: {
  sh: { checks?: Record<string, { status?: string }> } | undefined
  ov:
    | { disk?: { input_dir?: { total: number; used: number; free: number }; files_dir?: { total: number; used: number; free: number } } }
    | undefined
}) {
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
        <InfraRow
          label="Disco entrada"
          status={getDiskStatus(ov?.disk?.input_dir)}
          detail={formatDiskSpace(ov?.disk?.input_dir)}
        />
        <InfraRow
          label="Disco archivos"
          status={getDiskStatus(ov?.disk?.files_dir)}
          detail={formatDiskSpace(ov?.disk?.files_dir)}
        />
      </CardContent>
    </Card>
  )
}

function InfraRow({
  label,
  status,
  detail,
}: {
  label: string
  status: InfraStatus
  detail?: string
}) {
  return (
    <div className="flex items-center justify-between rounded-md border border-[var(--border)] bg-transparent px-3 py-2 text-[13px]">
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            status === "ok"
              ? "bg-[var(--positive)]"
              : status === "warning"
                ? "bg-[var(--warning)]"
                : status === "error"
                  ? "bg-[var(--danger)]"
                  : "bg-[var(--text-muted)]",
          )}
        />
        <span className="text-[var(--text-secondary)]">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        {detail && (
          <span className="font-mono text-[11px] tabular-nums text-[var(--text-muted)]">
            {detail}
          </span>
        )}
        <Badge
          variant={
            status === "ok"
              ? "success"
              : status === "warning"
                ? "warning"
                : status === "error"
                  ? "danger"
                  : "neutral"
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
// AlertsCard
// ---------------------------------------------------------------------------
type AlertItem = { key: string; title: string; description: string; severity: string; count: number }
export function AlertsCard({ alertItems }: { alertItems: AlertItem[] }) {
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
                  <p className="text-[11px] leading-relaxed text-[var(--text-muted)]">
                    {alert.description}
                  </p>
                </div>
                <Badge
                  variant={
                    alert.severity === "critical"
                      ? "danger"
                      : alert.severity === "warning"
                        ? "warning"
                        : "info"
                  }
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
// ShortcutsCard (the "Atajos" right-rail)
// ---------------------------------------------------------------------------
export function ShortcutsCard() {
  return (
    <ActionPanel
      title="Atajos"
      description="Tres accesos rápidos para las tareas más habituales."
    >
      <ShortcutLink to="/documents" icon={ScanLine} label="Escanear documentos" />
      <ShortcutLink to="/search" icon={Search} label="Buscar documentos" />
      <ShortcutLink to="/admin" icon={Activity} label="Panel de operación" />
    </ActionPanel>
  )
}

function ShortcutLink({
  to,
  icon: Icon,
  label,
}: {
  to: string
  icon: LucideIcon
  label: string
}) {
  return (
    <Button asChild variant="ghost" size="sm" className="w-full justify-between text-[13px]">
      <Link to={to}>
        <span className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-[var(--text-muted)]" /> {label}
        </span>
        <ArrowUpRight className="h-3.5 w-3.5 text-[var(--text-muted)]" />
      </Link>
    </Button>
  )
}

// Re-export OnboardingCallout wrapper for the page
export { OnboardingCallout } from "@/components/layout/OnboardingCallout"
export type { ReactNode }
