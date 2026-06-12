import type {
  Budget,
  BudgetLine,
  Invoice,
  Order,
  OrderLine,
  Plan,
  PlanDimension,
  PlanMeasurement,
  PlanRoom,
  ReconciliationIssue,
} from "@/types/api"
import { buildSearchParams, request } from "./core"

export const businessApi = {
  budgets: () => request<Budget[]>(`/budgets`),
  budgetLines: (id: number) => request<BudgetLine[]>(`/budgets/` + id + `/lines`),
  acceptedBudgetsWithoutOrder: () => request<Budget[]>(`/budgets/accepted-without-order`),
  orders: () => request<Order[]>(`/orders`),
  orderLines: (id: number) => request<OrderLine[]>(`/orders/` + id + `/lines`),
  invoices: (params?: { q?: string; limit?: number }) =>
    request<Invoice[]>(`/invoices` + buildSearchParams(params)),
  createInvoice: (payload: {
    document_id: number
    invoice_number?: string | null
    supplier_name?: string | null
    client_name?: string | null
    date?: string | null
    total_amount?: number | null
    currency?: string | null
    related_order_id?: number | null
    confidence?: number | null
  }) => request<Invoice>(`/invoices`, { method: "POST", body: JSON.stringify(payload) }),
  reconciliationIssues: () => request<ReconciliationIssue[]>(`/reconciliation/issues`),
  generateReconciliationIssues: () =>
    request<ReconciliationIssue[]>(`/reconciliation/issues/generate`, { method: "POST" }),
  updateReconciliationIssue: (
    id: number,
    payload: { status?: string; resolution_notes?: string | null },
  ) =>
    request<ReconciliationIssue>(`/reconciliation/issues/` + id, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  plans: () => request<Plan[]>(`/plans`),
  planRooms: (id: number) => request<PlanRoom[]>(`/plans/` + id + `/rooms`),
  planDimensions: (id: number) => request<PlanDimension[]>(`/plans/` + id + `/dimensions`),
  planMeasurements: (id: number) => request<PlanMeasurement[]>(`/plans/` + id + `/measurements`),
  createPlanMeasurement: (
    id: number,
    payload: {
      label: string
      page_number?: number | null
      measurement_type?: string
      value_m?: number | null
      ocr_value_m?: number | null
      points_json?: Record<string, unknown>[]
      calibration_json?: Record<string, unknown> | null
    },
  ) =>
    request<PlanMeasurement>(`/plans/` + id + `/measurements`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updatePlanScale: (
    id: number,
    payload: Partial<
      Pick<Plan, "scale_text" | "scale_ratio" | "scale_confidence" | "unit" | "has_valid_scale">
    >,
  ) =>
    request<Plan>(`/plans/` + id + `/scale`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  updatePlanRoom: (
    id: number,
    payload: Partial<
      Pick<
        PlanRoom,
        "name" | "area_m2" | "width_m" | "length_m" | "confidence" | "source" | "needs_review"
      >
    >,
  ) =>
    request<PlanRoom>(`/plan-rooms/` + id, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
}
