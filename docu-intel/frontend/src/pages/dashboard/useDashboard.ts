import { useQuery } from "@tanstack/react-query"

import { api } from "@/api/client"
import type { AdminStats } from "@/types/api"

// ---------------------------------------------------------------------------
// F8b-cont4 - dashboard hook
// ---------------------------------------------------------------------------
// Owns the six queries the dashboard renders, the first-time
// onboarding flag, the urgent-action list, and the pure helpers
// that convert the raw health/overview objects into a small
// "ok / warning / error / unknown" enum the UI can map to a
// coloured dot.
// ---------------------------------------------------------------------------

export type InfraStatus = "ok" | "warning" | "error" | "unknown"

export type UrgentAction = {
  label: string
  description: string
  to: string
  iconName: "ShieldAlert" | "FileWarning" | "AlertTriangle"
  count?: number
  tone: "danger" | "warning" | "info"
}

/** Map a check entry from the system health payload to a status. */
export function getCheckStatus(
  sh: { checks?: Record<string, { status?: string }> } | undefined,
  key: string,
): InfraStatus {
  const check = sh?.checks?.[key]
  if (!check?.status) return "unknown"
  if (check.status === "ok" || check.status === "healthy") return "ok"
  if (check.status === "warning" || check.status === "degraded") return "warning"
  return "error"
}

/** Map a disk-usage entry to a status based on percentage used. */
export function getDiskStatus(
  disk: { total: number; used: number; free: number } | undefined,
): InfraStatus {
  if (!disk || !disk.total) return "unknown"
  const pctUsed = disk.used / disk.total
  if (pctUsed > 0.9) return "error"
  if (pctUsed > 0.75) return "warning"
  return "ok"
}

/** Format a disk-usage entry as a short "X.X / Y.Y GB" string. */
export function formatDiskSpace(
  disk: { total: number; used: number; free: number } | undefined,
): string | undefined {
  if (!disk) return undefined
  const gbUsed = (disk.used / 1024 ** 3).toFixed(1)
  const gbTotal = (disk.total / 1024 ** 3).toFixed(1)
  return `${gbUsed} / ${gbTotal} GB`
}

/** Compute the dashboard's "urgent actions" list. Pure function. */
export function buildUrgentActions(
  stats: AdminStats | undefined,
  inbox: { kind: string; severity: string; document_id: number | null }[] | undefined,
): UrgentAction[] {
  const actions: UrgentAction[] = []
  const failed = inbox?.filter((i) => i.kind === "failed_job").length ?? 0
  if (failed > 0) {
    actions.push({
      label: "Jobs fallidos",
      description: `${failed} jobs requieren atención inmediata`,
      to: "/work-inbox",
      iconName: "ShieldAlert",
      count: failed,
      tone: "danger",
    })
  }
  const needsReview = stats?.documents_needs_review ?? 0
  if (needsReview > 0) {
    actions.push({
      label: "Documentos en revisión",
      description: `${needsReview} documentos pendientes de validación`,
      to: "/ocr-review",
      iconName: "FileWarning",
      count: needsReview,
      tone: "warning",
    })
  }
  const lowOcr = inbox?.filter((i) => i.kind === "low_ocr").length ?? 0
  if (lowOcr > 0) {
    actions.push({
      label: "OCR de baja confianza",
      description: `${lowOcr} páginas con OCR dudoso`,
      to: "/ocr-review",
      iconName: "FileWarning",
      count: lowOcr,
      tone: "warning",
    })
  }
  const budgetsWo = stats?.accepted_budgets_without_order ?? 0
  if (budgetsWo > 0) {
    actions.push({
      label: "Pptos. sin pedido",
      description: `${budgetsWo} presupuestos aceptados sin pedido asociado`,
      to: "/budgets",
      iconName: "AlertTriangle",
      count: budgetsWo,
      tone: "warning",
    })
  }
  return actions.slice(0, 4)
}

export function useDashboard() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats })
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts })
  const metrics = useQuery({ queryKey: ["processing-metrics"], queryFn: api.processingMetrics })
  const inbox = useQuery({
    queryKey: ["work-inbox"],
    queryFn: () => api.workInbox({ limit: 50 }),
    refetchInterval: 15_000,
  })
  const overview = useQuery({
    queryKey: ["operations-overview"],
    queryFn: api.operationsOverview,
    refetchInterval: 15_000,
  })
  const systemHealth = useQuery({
    queryKey: ["system-health"],
    queryFn: api.systemHealth,
    refetchInterval: 30_000,
  })

  const d = stats.data
  const ov = overview.data
  const sh = systemHealth.data
  const inboxItems = inbox.data ?? []
  const alertItems = alerts.data ?? []

  const urgentActions = buildUrgentActions(d, inboxItems)
  const isFirstTime = !stats.isLoading && (d?.documents_total ?? 0) === 0
  const isLoading = stats.isLoading

  return {
    stats,
    alerts,
    metrics,
    inbox,
    overview,
    systemHealth,
    d,
    ov,
    sh,
    inboxItems,
    alertItems,
    urgentActions,
    isFirstTime,
    isLoading,
  }
}

export type Dashboard = ReturnType<typeof useDashboard>
