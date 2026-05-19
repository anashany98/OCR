import { describe, expect, it } from "vitest"

import { buildTodaySnapshot, workInboxTarget } from "@/lib/operations"
import type { AdminAlert, AdminStats, OperationsOverview, WorkInboxItem } from "@/types/api"

describe("buildTodaySnapshot", () => {
  it("derives the operational today metrics from stats, alerts, inbox and queues", () => {
    const stats = {
      documents_total: 120,
      documents_processed: 80,
      documents_pending: 12,
      documents_failed: 3,
      documents_needs_review: 9,
      duplicates: 2,
      ocr_errors: 4,
      accepted_budgets_without_order: 5,
      plans_without_valid_scale: 6,
    } satisfies AdminStats
    const alerts = [
      { key: "jobs", title: "Jobs fallidos", description: "", severity: "critical", count: 3, action_url: "/jobs" },
      { key: "plans", title: "Planos", description: "", severity: "warning", count: 6, action_url: "/plans" },
    ] satisfies AdminAlert[]
    const inbox = [
      item("failed_job", "error"),
      item("low_ocr", "warning"),
      item("needs_human_review", "warning"),
    ]
    const overview = {
      jobs: { pending_or_processing: 8, estimated_remaining_seconds: 1800 },
      queues: { backpressure_active: true },
      documents: { low_ocr_pages: 7 },
    } as OperationsOverview

    expect(buildTodaySnapshot({ stats, alerts, inbox, overview })).toEqual({
      processedDocuments: 80,
      pendingDocuments: 12,
      reviewDocuments: 9,
      criticalAlerts: 1,
      openWorkItems: 3,
      pendingJobs: 8,
      lowOcrPages: 7,
      backpressureActive: true,
      etaLabel: "30 min",
    })
  })

  it("uses safe defaults when optional feeds have not loaded yet", () => {
    expect(buildTodaySnapshot({})).toEqual({
      processedDocuments: 0,
      pendingDocuments: 0,
      reviewDocuments: 0,
      criticalAlerts: 0,
      openWorkItems: 0,
      pendingJobs: 0,
      lowOcrPages: 0,
      backpressureActive: false,
      etaLabel: "-",
    })
  })
})

describe("workInboxTarget", () => {
  it("routes OCR items to review and document items to the document workspace", () => {
    expect(workInboxTarget(item("low_ocr", "warning", { page_id: 10, document_id: 4 }))).toBe("/ocr-review")
    expect(workInboxTarget(item("failed_job", "error", { job_id: 8 }))).toBe("/jobs")
    expect(workInboxTarget(item("missing_fields", "warning", { document_id: 11 }))).toBe("/documents/11")
  })
})

function item(kind: string, severity: string, overrides: Partial<WorkInboxItem> = {}): WorkInboxItem {
  return {
    kind,
    severity,
    title: kind,
    description: "",
    document_id: null,
    page_id: null,
    job_id: null,
    action_url: null,
    status: null,
    created_at: null,
    ...overrides,
  }
}
