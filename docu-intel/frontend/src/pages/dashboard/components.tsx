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

const ICON_MAP: Record<string, LucideIcon> = { ShieldAlert, FileWarning, AlertTriangle }

// ---------------------------------------------------------------------------
// DashboardHero — clean SaaS header
// ---------------------------------------------------------------------------
export function DashboardHero({
  stats,
  isLoading,
}: {
  stats: AdminStats | undefined
  isLoading: boolean
}) {
  const processedCount = useCountUp(isLoading ? 0 : (stats?.documents_processed ?? 0), 900)
  const totalCount = useCountUp(isLoading ? 0 : (stats?.documents_total ?? 0), 1100)
  const today = new Date().toLocaleDateString("es-ES", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  })
  return (
    <header
      className="rounded-xl border border-[var(--border)] p-6 md:p-8"
      style={{ background: "linear-gradient(135deg, var(--accent) 0%, #7c3aed 100%)" }}
    >
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0 space-y-1">
          <p className="text-[11px] font-medium uppercase tracking-wider text-white/60">{today}</p>
          <h1 className="text-[28px] font-bold leading-tight text-white md:text-[34px]">
            {totalCount > 0 ? (
              <>{totalCount.toLocaleString("es-ES")} documentos</>
            ) : (
              "Tu centro de trabajo documental"
            )}
          </h1>
          <p className="text-[13px] text-white/70">
            Vista general del procesamiento y las tareas que necesitan atención.
          </p>
        </div>
        <div className="flex items-end gap-8">
          <div className="text-right">
            <p className="text-[10px] font-medium uppercase tracking-wider text-white/50">
              Procesados hoy
            </p>
            <p className="text-[42px] font-bold leading-none tabular-nums text-white">
              {isLoading ? "—" : processedCount.toLocaleString("es-ES")}
            </p>
          </div>
        </div>
      </div>
    </header>
  )
}

// ---------------------------------------------------------------------------
// UrgentActionCard — compact action tile
// ---------------------------------------------------------------------------
export function UrgentActionCard({ action }: { action: UrgentAction }) {
  const Icon = ICON_MAP[action.iconName] ?? ShieldAlert
  const { ring, accentText, accentIcon, badgeBg } = (() => {
    switch (action.tone) {
      case "danger":
        return {
          ring: "border-[var(--danger)]/20 bg-[var(--danger-faint)]",
          accentText: "text-[var(--text-on-danger)]",
          accentIcon: "text-[var(--danger)]",
          badgeBg: "bg-[var(--danger)]",
        }
      case "warning":
        return {
          ring: "border-[var(--warning)]/20 bg-[var(--warning-faint)]",
          accentText: "text-[var(--text-on-warning)]",
          accentIcon: "text-[var(--warning)]",
          badgeBg: "bg-[var(--warning)]",
        }
      default:
        return {
          ring: "border-[var(--info)]/20 bg-[var(--info-faint)]",
          accentText: "text-[var(--text-on-info)]",
          accentIcon: "text-[var(--info)]",
          badgeBg: "bg-[var(--info)]",
        }
    }
  })()

  return (
    <Link
      to={action.to}
      className={cn(
        "group relative flex flex-col gap-1.5 rounded-lg border p-3.5 transition-all hover:shadow-sm",
        ring,
      )}
    >
      <div className="flex items-start justify-between">
        <Icon className={cn("h-4 w-4", accentIcon)} aria-hidden="true" />
        {action.count != null && action.count > 0 && (
          <span
            className={cn(
              "flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[10px] font-semibold text-white",
              badgeBg,
            )}
          >
            {action.count > 99 ? "99+" : action.count}
          </span>
        )}
      </div>
      <p className={cn("text-[13px] font-semibold leading-tight", accentText)}>{action.label}</p>
      <p className="text-[11px] text-[var(--text-muted)] leading-snug">{action.description}</p>
      <ArrowRight className="absolute bottom-2.5 right-2.5 h-3 w-3 text-[var(--text-muted)] opacity-0 transition-all group-hover:opacity-100" />
    </Link>
  )
}

export function UrgentActionsSection({ actions }: { actions: UrgentAction[] }) {
  if (!actions.length) return null
  return (
    <section>
      <div className="mb-2 flex items-baseline gap-2">
        <h2 className="text-[13px] font-semibold text-[var(--text-primary)]">Atención inmediata</h2>
        <span className="text-[11px] text-[var(--text-muted)]">{actions.length} asuntos</span>
      </div>
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
        {actions.map((a) => (
          <UrgentActionCard key={a.to + a.label} action={a} />
        ))}
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// MetricStrip — compact KPI row
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
      <h2 className="mb-2 text-[13px] font-semibold text-[var(--text-primary)]">
        Operación de hoy
      </h2>
      <div className="grid gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
        <MetricTile
          title="Procesados"
          value={isLoading ? "—" : (stats?.documents_processed ?? 0)}
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
          value={isLoading ? "—" : (stats?.documents_failed ?? 0)}
          meta="Requieren atención"
          tone={(stats?.documents_failed ?? 0) > 0 ? "danger" : "success"}
          icon={<AlertTriangle className="h-4 w-4" />}
        />
        <MetricTile
          title="Revisión"
          value={isLoading ? "—" : (stats?.documents_needs_review ?? 0)}
          meta="Sin cola"
          tone={(stats?.documents_needs_review ?? 0) > 0 ? "warning" : "neutral"}
          icon={<FileWarning className="h-4 w-4" />}
        />
        <MetricTile
          title="Pipeline"
          value={ov?.jobs.pending_or_processing ?? "—"}
          meta="Workers"
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
// PriorityWorkCard — dense list
// ---------------------------------------------------------------------------
type InboxItem = {
  kind: string
  severity: string
  title: string
  description: string
  action_url: string | null
  document_id: number | null
}

export function PriorityWorkCard({ inboxItems }: { inboxItems: InboxItem[] }) {
  return (
    <Card>
      <CardHeader className="flex-row items-baseline justify-between pb-3">
        <div>
          <CardTitle className="text-[14px]">Trabajo prioritario</CardTitle>
          <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
            {inboxItems.length > 0 ? `${inboxItems.length} incidencias abiertas` : "Bandeja vacía"}
          </p>
        </div>
        <Button asChild variant="ghost" size="sm" className="text-[11px] text-[var(--accent)] h-7">
          <Link to="/work-inbox">
            Ver todas <ArrowRight className="ml-1 h-3 w-3" />
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="px-0 py-0">
        {inboxItems.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--success-faint)] text-[var(--success)]">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <p className="text-[13px] font-medium text-[var(--text-primary)]">
              Sin trabajo pendiente
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {inboxItems.slice(0, 6).map((item, i) => (
              <li key={`${item.kind}-${item.document_id ?? "d"}-${i}`}>
                <Link
                  to={item.action_url || "/work-inbox"}
                  className="group flex items-center gap-3 px-5 py-3 hover:bg-[var(--bg-surface-2)]/60 transition-colors"
                >
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full flex-shrink-0",
                      item.severity === "error" || item.severity === "critical"
                        ? "bg-[var(--danger)]"
                        : item.severity === "warning"
                          ? "bg-[var(--warning)]"
                          : "bg-[var(--info)]",
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[12px] font-medium text-[var(--text-primary)]">
                      {item.title}
                    </p>
                    <p className="truncate text-[11px] text-[var(--text-muted)]">
                      {item.description}
                    </p>
                  </div>
                  <ArrowRight className="h-3 w-3 text-[var(--text-muted)] opacity-0 group-hover:opacity-100 flex-shrink-0" />
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
// DistributionCard — horizontal bars
// ---------------------------------------------------------------------------
export function DistributionCard({
  metrics,
}: {
  metrics:
    | {
        documents_by_status?: Record<string, number>
        documents_by_type?: Record<string, number>
        jobs_by_status?: Record<string, number>
      }
    | undefined
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-[14px]">Distribución</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-5 sm:grid-cols-3">
          <DistributionColumn title="Por estado" values={metrics?.documents_by_status} />
          <DistributionColumn title="Por tipo" values={metrics?.documents_by_type} />
          <DistributionColumn title="Jobs" values={metrics?.jobs_by_status} />
        </div>
      </CardContent>
    </Card>
  )
}

function DistributionColumn({ title, values }: { title: string; values?: Record<string, number> }) {
  const entries = Object.entries(values ?? {}).slice(0, 6)
  const total = entries.reduce((sum, [, n]) => sum + n, 0)
  return (
    <div className="space-y-2">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        {title}
      </p>
      <div className="space-y-1.5">
        {entries.map(([key, count]) => {
          const pct = total > 0 ? (count / total) * 100 : 0
          return (
            <div key={key} className="space-y-0.5">
              <div className="flex items-center justify-between text-[11px]">
                <span className="truncate capitalize text-[var(--text-secondary)]">
                  {key.replace(/_/g, " ")}
                </span>
                <span className="font-mono tabular-nums text-[var(--text-muted)]">{count}</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-[var(--bg-surface-2)]">
                <div
                  className="h-full rounded-full bg-[var(--accent)]"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          )
        })}
        {entries.length === 0 && <p className="text-[11px] text-[var(--text-muted)]">Sin datos</p>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// InfrastructureCard — compact status rows
// ---------------------------------------------------------------------------
export function InfrastructureCard({
  sh,
  ov,
}: {
  sh: { checks?: Record<string, { status?: string }> } | undefined
  ov:
    | {
        disk?: {
          input_dir?: { total: number; used: number; free: number }
          files_dir?: { total: number; used: number; free: number }
        }
      }
    | undefined
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-[14px]">Infraestructura</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5">
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
  const dotColor =
    status === "ok"
      ? "bg-[var(--success)]"
      : status === "warning"
        ? "bg-[var(--warning)]"
        : status === "error"
          ? "bg-[var(--danger)]"
          : "bg-[var(--text-muted)]"
  const badgeVariant =
    status === "ok"
      ? "success"
      : status === "warning"
        ? "warning"
        : status === "error"
          ? "danger"
          : "neutral"
  return (
    <div className="flex items-center justify-between rounded-md px-2.5 py-1.5 text-[12px]">
      <div className="flex items-center gap-2">
        <span className={cn("h-1.5 w-1.5 rounded-full", dotColor)} />
        <span className="text-[var(--text-secondary)]">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        {detail && (
          <span className="font-mono text-[10px] tabular-nums text-[var(--text-muted)]">
            {detail}
          </span>
        )}
        <Badge variant={badgeVariant} className="text-[9px] px-1.5 py-0">
          {status === "ok"
            ? "OK"
            : status === "warning"
              ? "WARN"
              : status === "error"
                ? "FAIL"
                : "—"}
        </Badge>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// AlertsCard — compact
// ---------------------------------------------------------------------------
type AlertItem = {
  key: string
  title: string
  description: string
  severity: string
  count: number
}

export function AlertsCard({ alertItems }: { alertItems: AlertItem[] }) {
  return (
    <Card>
      <CardHeader className="flex-row items-baseline justify-between pb-3">
        <CardTitle className="text-[14px]">Alertas</CardTitle>
        {alertItems.length > 0 && (
          <Badge variant="warning" className="text-[10px]">
            {alertItems.length}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="px-0 py-0">
        {alertItems.length === 0 ? (
          <p className="py-6 text-center text-[11px] text-[var(--text-muted)]">
            Sin alertas activas
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {alertItems.slice(0, 4).map((a) => (
              <li key={a.key} className="flex items-start justify-between gap-3 px-5 py-2.5">
                <div className="min-w-0">
                  <p className="text-[12px] font-medium text-[var(--text-primary)]">{a.title}</p>
                  <p className="text-[10px] text-[var(--text-muted)]">{a.description}</p>
                </div>
                <Badge
                  variant={
                    a.severity === "critical"
                      ? "danger"
                      : a.severity === "warning"
                        ? "warning"
                        : "info"
                  }
                  className="text-[10px] flex-shrink-0"
                >
                  {a.count}
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
// ShortcutsCard
// ---------------------------------------------------------------------------
export function ShortcutsCard() {
  return (
    <ActionPanel title="Atajos" description="Accesos rápidos.">
      <ShortcutLink to="/documents" icon={ScanLine} label="Escanear documentos" />
      <ShortcutLink to="/search" icon={Search} label="Buscar documentos" />
      <ShortcutLink to="/admin" icon={Activity} label="Panel de operación" />
    </ActionPanel>
  )
}

function ShortcutLink({ to, icon: Icon, label }: { to: string; icon: LucideIcon; label: string }) {
  return (
    <Button asChild variant="ghost" size="sm" className="w-full justify-between text-[12px] h-8">
      <Link to={to}>
        <span className="flex items-center gap-2">
          <Icon className="h-3.5 w-3.5 text-[var(--text-muted)]" /> {label}
        </span>
        <ArrowUpRight className="h-3 w-3 text-[var(--text-muted)]" />
      </Link>
    </Button>
  )
}

export { OnboardingCallout } from "@/components/layout/OnboardingCallout"
export type { ReactNode }
