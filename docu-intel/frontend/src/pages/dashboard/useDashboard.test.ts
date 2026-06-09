import { describe, expect, it } from "vitest"

import {
  buildUrgentActions,
  formatDiskSpace,
  getCheckStatus,
  getDiskStatus,
  type UrgentAction,
} from "./useDashboard"

describe("getCheckStatus", () => {
  it("returns 'ok' for healthy checks", () => {
    expect(getCheckStatus({ checks: { database: { status: "ok" } } }, "database")).toBe("ok")
    expect(getCheckStatus({ checks: { database: { status: "healthy" } } }, "database")).toBe("ok")
  })

  it("returns 'warning' for degraded checks", () => {
    expect(getCheckStatus({ checks: { redis: { status: "warning" } } }, "redis")).toBe("warning")
    expect(getCheckStatus({ checks: { redis: { status: "degraded" } } }, "redis")).toBe("warning")
  })

  it("returns 'error' for everything else", () => {
    expect(getCheckStatus({ checks: { celery: { status: "down" } } }, "celery")).toBe("error")
  })

  it("returns 'unknown' when the check is missing", () => {
    expect(getCheckStatus(undefined, "database")).toBe("unknown")
    expect(getCheckStatus({}, "database")).toBe("unknown")
    expect(getCheckStatus({ checks: {} }, "database")).toBe("unknown")
  })
})

describe("getDiskStatus", () => {
  it("returns 'ok' when usage is under 75 %", () => {
    expect(getDiskStatus({ total: 100, used: 50, free: 50 })).toBe("ok")
    expect(getDiskStatus({ total: 100, used: 74, free: 26 })).toBe("ok")
  })

  it("returns 'warning' when usage is between 75 and 90 %", () => {
    expect(getDiskStatus({ total: 100, used: 80, free: 20 })).toBe("warning")
  })

  it("returns 'error' when usage is over 90 %", () => {
    expect(getDiskStatus({ total: 100, used: 95, free: 5 })).toBe("error")
  })

  it("returns 'unknown' for missing or zero-total disks", () => {
    expect(getDiskStatus(undefined)).toBe("unknown")
    expect(getDiskStatus({ total: 0, used: 0, free: 0 })).toBe("unknown")
  })
})

describe("formatDiskSpace", () => {
  it("formats a typical disk in GB with one decimal", () => {
    // 1 TB = 1024^4 bytes = 1024 GB; 512 GB used; 512 GB free.
    const disk = {
      total: 1024 * 1024 * 1024 * 1024,
      used: 512 * 1024 * 1024 * 1024,
      free: 512 * 1024 * 1024 * 1024,
    }
    expect(formatDiskSpace(disk)).toBe("512.0 / 1024.0 GB")
  })

  it("returns undefined for missing disk", () => {
    expect(formatDiskSpace(undefined)).toBeUndefined()
  })
})

describe("buildUrgentActions", () => {
  it("returns an empty list when there are no issues", () => {
    expect(buildUrgentActions(undefined, [])).toEqual([])
  })

  it("emits a 'Jobs fallidos' action when the inbox has failed_job items", () => {
    const actions = buildUrgentActions(undefined, [
      { kind: "failed_job", severity: "critical", document_id: 1 },
      { kind: "failed_job", severity: "critical", document_id: 2 },
    ])
    expect(actions).toContainEqual(
      expect.objectContaining({ label: "Jobs fallidos", count: 2, tone: "danger" }),
    )
  })

  it("emits a 'Documentos en revisión' action when stats has needs_review", () => {
    const actions = buildUrgentActions(
      { documents_needs_review: 5 } as never,
      [],
    )
    expect(actions).toContainEqual(
      expect.objectContaining({ label: "Documentos en revisión", count: 5, tone: "warning" }),
    )
  })

  it("emits a 'OCR de baja confianza' action for low_ocr items", () => {
    const actions = buildUrgentActions(undefined, [
      { kind: "low_ocr", severity: "warning", document_id: null },
      { kind: "low_ocr", severity: "warning", document_id: null },
      { kind: "low_ocr", severity: "warning", document_id: null },
    ])
    expect(actions).toContainEqual(
      expect.objectContaining({ label: "OCR de baja confianza", count: 3 }),
    )
  })

  it("caps the list at 4 entries", () => {
    const actions = buildUrgentActions(
      {
        documents_needs_review: 5,
        accepted_budgets_without_order: 5,
      } as never,
      [
        { kind: "failed_job", severity: "critical", document_id: 1 },
        { kind: "low_ocr", severity: "warning", document_id: null },
      ],
    )
    expect(actions.length).toBeLessThanOrEqual(4)
  })

  it("returns the actions with the right shape", () => {
    const actions: UrgentAction[] = buildUrgentActions(undefined, [
      { kind: "failed_job", severity: "critical", document_id: 1 },
    ])
    expect(actions[0]).toEqual(
      expect.objectContaining({
        label: expect.any(String),
        description: expect.any(String),
        to: expect.any(String),
        iconName: expect.stringMatching(/^(ShieldAlert|FileWarning|AlertTriangle)$/),
        count: expect.any(Number),
        tone: expect.stringMatching(/^(danger|warning|info)$/),
      }),
    )
  })
})
