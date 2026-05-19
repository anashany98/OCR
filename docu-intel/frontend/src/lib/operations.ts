import type { AdminAlert, AdminStats, OperationsOverview, WorkInboxItem } from "@/types/api"

export type TodaySnapshot = {
  processedDocuments: number
  pendingDocuments: number
  reviewDocuments: number
  criticalAlerts: number
  openWorkItems: number
  pendingJobs: number
  lowOcrPages: number
  backpressureActive: boolean
  etaLabel: string
}

export function buildTodaySnapshot({
  stats,
  alerts,
  inbox,
  overview,
}: {
  stats?: AdminStats
  alerts?: AdminAlert[]
  inbox?: WorkInboxItem[]
  overview?: OperationsOverview
}): TodaySnapshot {
  return {
    processedDocuments: stats?.documents_processed ?? 0,
    pendingDocuments: stats?.documents_pending ?? 0,
    reviewDocuments: stats?.documents_needs_review ?? 0,
    criticalAlerts: (alerts ?? []).filter((alert) => alert.severity === "critical" || alert.severity === "error").length,
    openWorkItems: inbox?.length ?? 0,
    pendingJobs: overview?.jobs.pending_or_processing ?? 0,
    lowOcrPages: overview?.documents.low_ocr_pages ?? 0,
    backpressureActive: overview?.queues.backpressure_active ?? false,
    etaLabel: formatEta(overview?.jobs.estimated_remaining_seconds),
  }
}

export function workInboxTarget(item: WorkInboxItem): string {
  if (item.kind === "low_ocr" || item.page_id) return "/ocr-review"
  if (item.job_id) return "/jobs"
  if (item.kind === "accepted_budget_without_order") return "/budgets"
  if (item.document_id) return "/documents/" + item.document_id
  return item.action_url ?? "/"
}

export function formatEta(seconds: number | null | undefined): string {
  if (!seconds || seconds < 1) return "-"
  if (seconds < 60) return "<1 min"
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return minutes + " min"
  const hours = Math.round(minutes / 60)
  return hours + " h"
}
