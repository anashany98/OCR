import { afterEach, describe, expect, it, vi } from "vitest"

import { api, documentPreviewUrl, downloadUrl, pageImageUrl } from "@/api/client"

afterEach(() => {
  vi.restoreAllMocks()
})

describe("downloadUrl", () => {
  it("builds a protected download endpoint", () => {
    expect(downloadUrl(42)).toContain("/documents/42/download")
  })
})

describe("pageImageUrl", () => {
  it("builds a protected OCR page preview endpoint", () => {
    expect(pageImageUrl(42, 3)).toContain("/documents/42/pages/3/image")
  })
})

describe("documentPreviewUrl", () => {
  it("builds a protected generated document preview endpoint", () => {
    expect(documentPreviewUrl(42)).toContain("/documents/42/preview")
  })
})

describe("new operations API client methods", () => {
  it("calls guided search with the selected mode", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse([]))

    await api.guidedSearch("ABC123", "reference")

    expect(String(fetchMock.mock.calls[0][0])).toContain("/search/guided?mode=reference&q=ABC123")
  })

  it("posts work inbox actions", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        action: "retry_failed_jobs",
        matched: 1,
        updated: 0,
        enqueued: 1,
        job_ids: [9],
      }),
    )

    await api.runWorkInboxAction({ action: "retry_failed_jobs", limit: 10 })

    const [, init] = fetchMock.mock.calls[0]
    expect(String(fetchMock.mock.calls[0][0])).toContain("/admin/work-inbox/actions")
    expect(init?.method).toBe("POST")
    expect(JSON.parse(String(init?.body))).toEqual({ action: "retry_failed_jobs", limit: 10 })
  })

  it("posts redaction preview requests", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ redacted_text: "Total [IMPORTE OCULTO]" }))

    await api.redactionPreview({
      principal_type: "technician",
      principal_id: "tech-1",
      text: "Total 99,00 €",
    })

    expect(String(fetchMock.mock.calls[0][0])).toContain("/admin/security/redaction-preview")
  })

  it("loads production readiness checks", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ status: "ready", checks: [] }))

    await api.productionReadiness()

    expect(String(fetchMock.mock.calls[0][0])).toContain("/admin/production/readiness")
  })

  it("loads data quality summary", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ rules: {}, by_quality_status: {} }))

    await api.qualitySummary()

    expect(String(fetchMock.mock.calls[0][0])).toContain("/admin/quality/summary")
  })

  it("posts bulk document tags", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ matched: 1, updated: 1 }))

    await api.bulkDocumentTags({ document_ids: [7], add_tags: ["contabilidad"], remove_tags: [] })

    expect(String(fetchMock.mock.calls[0][0])).toContain("/admin/documents/bulk-tags")
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      document_ids: [7],
      add_tags: ["contabilidad"],
      remove_tags: [],
    })
  })

  it("creates persisted work item comments", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ id: 4, body: "Revisado" }))

    await api.addWorkItemComment(3, { body: "Revisado" })

    expect(String(fetchMock.mock.calls[0][0])).toContain("/admin/work-items/3/comments")
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST")
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({ body: "Revisado" })
  })

  it("posts OCR revisions for document pages", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({ id: 9 }))

    await api.createOcrRevision(12, {
      corrected_text: "Texto corregido",
      reason: "Corrección manual",
    })

    expect(String(fetchMock.mock.calls[0][0])).toContain("/documents/pages/12/ocr-revisions")
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST")
  })

  it("saves document search presets", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ id: 8, name: "Facturas" }))

    await api.createSavedSearch({
      name: "Facturas",
      query: "factura",
      mode: "hybrid",
      filters_json: { document_type: "invoice" },
    })

    expect(String(fetchMock.mock.calls[0][0])).toContain("/search/saved")
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      name: "Facturas",
      query: "factura",
      mode: "hybrid",
      filters_json: { document_type: "invoice" },
    })
  })

  it("generates and updates reconciliation issues", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ id: 5, status: "reviewed" }))

    await api.generateReconciliationIssues()
    await api.updateReconciliationIssue(5, {
      status: "reviewed",
      resolution_notes: "Validado por compras",
    })

    expect(String(fetchMock.mock.calls[0][0])).toContain("/reconciliation/issues/generate")
    expect(String(fetchMock.mock.calls[1][0])).toContain("/reconciliation/issues/5")
    expect(fetchMock.mock.calls[1][1]?.method).toBe("PATCH")
  })

  it("creates invoices for reconciliation", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ id: 7, invoice_number: "F-1" }))

    await api.createInvoice({ document_id: 3, invoice_number: "F-1", total_amount: 99 })

    expect(String(fetchMock.mock.calls[0][0])).toContain("/invoices")
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST")
  })

  it("records manual plan measurements", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(jsonResponse({ id: 6, has_discrepancy: true }))

    await api.createPlanMeasurement(2, {
      label: "Largo pasillo",
      value_m: 3.4,
      ocr_value_m: 3.1,
      points_json: [],
    })

    expect(String(fetchMock.mock.calls[0][0])).toContain("/plans/2/measurements")
    expect(fetchMock.mock.calls[0][1]?.method).toBe("POST")
  })
})

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  } as Response
}
