import type {
  AdminAlert,
  AdminStats,
  AdminUser,
  AccessGroup,
  AccessGroupMember,
  AccessExplain,
  EffectiveAccess,
  AIAnswer,
  AIQuestion,
  AuditLog,
  Budget,
  BudgetLine,
  BulkReprocessResponse,
  Document,
  DocumentBlock,
  DocumentEntity,
  DocumentGraph,
  DocumentPage,
  DocumentTimelineEvent,
  FolderRule,
  Hotel,
  HotelChain,
  NotificationRule,
  OcrRevision,
  IngestionEvent,
  IntegrationToolResponse,
  IntegrationClient,
  Invoice,
  PlanMeasurement,
  Job,
  MaintenanceReport,
  OcrReviewPage,
  Order,
  OrderLine,
  BulkTagsResponse,
  OperationsStatus,
  OperationsOverview,
  PaginatedDocuments,
  Plan,
  PlanDimension,
  PlanRoom,
  ProcessingMetrics,
  ProductionChecklist,
  ProductionReadiness,
  QualityRecalculateResponse,
  QualityRules,
  QualitySummary,
  QueueStatus,
  RedactionPreview,
  ReconciliationIssue,
  RulePreview,
  SavedSearch,
  SavedView,
  SearchResult,
  SensitiveTag,
  StorageIntegrity,
  SystemHealth,
  User,
  WatchedFile,
  WorkInboxActionResponse,
  WorkInboxItem,
  WorkItem,
  WorkItemComment,
} from "@/types/api"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api"

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}` + path, {
    credentials: "include",
    headers: options.body instanceof FormData ? options.headers : { "Content-Type": "application/json", ...options.headers },
    ...options,
  })
  if (!response.ok) {
    let message = response.statusText
    try {
      const payload = await response.json()
      message = payload.detail || message
    } catch {
    }
    throw new ApiError(message, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export interface BatchUploadResult {
  uploaded: number
  duplicates: number
  failed: number
  documents: { document_id: number; original_filename: string; status: string; job_id: number | null }[]
}

export function thumbnailUrl(documentId: number) {
  return `${API_BASE_URL}` + "/documents/" + documentId + "/thumbnail"
}

export function pageImageUrl(documentId: number, pageNumber: number) {
  return `${API_BASE_URL}` + "/documents/" + documentId + "/pages/" + pageNumber + "/image"
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; user: User }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<User>("/auth/me"),
  stats: () => request<AdminStats>("/admin/stats"),
  alerts: () => request<AdminAlert[]>("/admin/alerts"),
  processingMetrics: () => request<ProcessingMetrics>("/admin/processing-metrics"),
  systemMetrics: () => request<ProcessingMetrics>("/admin/system/metrics"),
  systemHealth: () => request<SystemHealth>("/admin/system/health"),
  queues: () => request<QueueStatus>("/admin/queues"),
  pauseQueues: () => request<QueueStatus>("/admin/queues/pause", { method: "POST" }),
  resumeQueues: () => request<QueueStatus>("/admin/queues/resume", { method: "POST" }),
  workInbox: (params?: { max_ocr_confidence?: number; limit?: number }) =>
    request<WorkInboxItem[]>("/admin/work-inbox" + buildSearchParams(params)),
  runWorkInboxAction: (payload: { action: string; limit?: number; min_confidence?: number }) =>
    request<WorkInboxActionResponse>("/admin/work-inbox/actions", { method: "POST", body: JSON.stringify(payload) }),
  workItems: (params?: { status?: string; priority?: string; limit?: number }) =>
    request<WorkItem[]>("/admin/work-items" + buildSearchParams(params)),
  createWorkItem: (payload: {
    kind: string
    title: string
    description?: string
    priority?: string
    document_id?: number | null
    page_id?: number | null
    job_id?: number | null
    assignee_user_id?: number | null
    due_at?: string | null
  }) => request<WorkItem>("/admin/work-items", { method: "POST", body: JSON.stringify(payload) }),
  updateWorkItem: (id: number, payload: { status?: string; priority?: string; assignee_user_id?: number | null; due_at?: string | null; resolution_notes?: string | null }) =>
    request<WorkItem>("/admin/work-items/" + id, { method: "PATCH", body: JSON.stringify(payload) }),
  addWorkItemComment: (id: number, payload: { body: string }) =>
    request<WorkItemComment>("/admin/work-items/" + id + "/comments", { method: "POST", body: JSON.stringify(payload) }),
  savedViews: (scope = "documents") => request<SavedView[]>("/admin/saved-views" + buildSearchParams({ scope })),
  createSavedView: (payload: { name: string; scope?: string; filters_json?: Record<string, unknown>; is_shared?: boolean }) =>
    request<SavedView>("/admin/saved-views", { method: "POST", body: JSON.stringify(payload) }),
  notificationRules: () => request<NotificationRule[]>("/admin/notification-rules"),
  createNotificationRule: (payload: { name: string; event_type: string; channel: string; target: string; is_active?: boolean; filters_json?: Record<string, unknown> }) =>
    request<NotificationRule>("/admin/notification-rules", { method: "POST", body: JSON.stringify(payload) }),
  adminUsers: () => request<AdminUser[]>("/admin/users"),
  createAdminUser: (payload: { email: string; name: string; role: string; password: string; is_active?: boolean }) =>
    request<AdminUser>("/admin/users", { method: "POST", body: JSON.stringify(payload) }),
  updateAdminUser: (id: number, payload: { name?: string; role?: string; is_active?: boolean; password?: string }) =>
    request<AdminUser>("/admin/users/" + id, { method: "PATCH", body: JSON.stringify(payload) }),
  seedDemo: () => request<{ seeded: boolean }>("/admin/demo/seed", { method: "POST" }),
  productionChecklist: () => request<ProductionChecklist>("/admin/production/checklist"),
  rulePreview: (payload: { path: string; pattern: string; match_type?: "contains" | "glob" | "regex"; tags_json?: string[] }) =>
    request<RulePreview>("/admin/rules/preview", { method: "POST", body: JSON.stringify(payload) }),
  integrationSandbox: (payload: { client_id: number; technician_id: string; technician_name?: string | null; tool: string; arguments: Record<string, unknown> }) =>
    request<IntegrationToolResponse>("/admin/integration-sandbox/execute", { method: "POST", body: JSON.stringify(payload) }),
  redactionPreview: (payload: { principal_type: "user" | "technician"; principal_id: string; text: string }) =>
    request<RedactionPreview>("/admin/security/redaction-preview", { method: "POST", body: JSON.stringify(payload) }),
  retryJob: (id: number) => request<Job>("/admin/jobs/" + id + "/retry", { method: "POST" }),
  cancelJob: (id: number) => request<Job>("/admin/jobs/" + id + "/cancel", { method: "POST" }),
  operationsStatus: () => request<OperationsStatus>("/admin/operations-status"),
  operationsOverview: () => request<OperationsOverview>("/admin/operations/overview"),
  operationsDocuments: (params?: { status?: string; document_type?: string; q?: string; quality_status?: string; limit?: number; offset?: number }) =>
    request<PaginatedDocuments>("/admin/operations/documents" + buildSearchParams(params)),
  maintenanceReport: () => request<MaintenanceReport>("/admin/maintenance-report"),
  productionReadiness: () => request<ProductionReadiness>("/admin/production/readiness"),
  storageIntegrity: (limit = 1000) => request<StorageIntegrity>("/admin/storage/integrity?limit=" + limit),
  qualityRules: () => request<QualityRules>("/admin/quality/rules"),
  qualitySummary: () => request<QualitySummary>("/admin/quality/summary"),
  recalculateQuality: (payload: { limit?: number }) =>
    request<QualityRecalculateResponse>("/admin/quality/recalculate", { method: "POST", body: JSON.stringify(payload) }),
  effectiveAccess: (params: { principal_type: "user" | "technician"; principal_id: string }) =>
    request<EffectiveAccess>("/admin/access/effective" + buildSearchParams(params)),
  bulkDocumentTags: (payload: { document_ids: number[]; add_tags?: string[]; remove_tags?: string[] }) =>
    request<BulkTagsResponse>("/admin/documents/bulk-tags", { method: "POST", body: JSON.stringify(payload) }),
  watchedFiles: () => request<WatchedFile[]>("/admin/watched-files?limit=50"),
  ingestionEvents: () => request<IngestionEvent[]>("/admin/ingestion-events?limit=50"),
  accessExplain: (params: { principal_type: "user" | "technician"; principal_id: string; document_id: number }) =>
    request<AccessExplain>("/admin/access-explain" + buildSearchParams(params)),
  documentGraph: (documentId: number) => request<DocumentGraph>("/admin/documents/" + documentId + "/graph"),
  auditLogs: () => request<AuditLog[]>("/admin/audit-logs"),
  integrationClients: () => request<IntegrationClient[]>("/admin/integration-clients"),
  createIntegrationClient: (payload: { name: string; scopes: string[]; is_active?: boolean }) =>
    request<IntegrationClient>("/admin/integration-clients", { method: "POST", body: JSON.stringify(payload) }),
  updateIntegrationClient: (id: number, payload: { name?: string; scopes?: string[]; is_active?: boolean }) =>
    request<IntegrationClient>("/admin/integration-clients/" + id, { method: "PATCH", body: JSON.stringify(payload) }),
  rotateIntegrationClientKey: (id: number) =>
    request<IntegrationClient>("/admin/integration-clients/" + id + "/rotate-key", { method: "POST" }),
  ocrReview: (params?: { max_confidence?: number; limit?: number; document_type?: string; status?: string; review_status?: string }) =>
    request<OcrReviewPage[]>("/admin/ocr-review" + buildSearchParams(params)),
  updateOcrReview: (pageId: number, payload: { review_status: "pending" | "approved" | "rejected"; review_notes?: string | null }) =>
    request<OcrReviewPage>("/admin/ocr-review/" + pageId, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  reprocessOcrPage: (pageId: number) => request<Job>("/admin/quality/pages/" + pageId + "/reprocess-ocr", { method: "POST" }),
  documents: () => request<Document[]>("/documents"),
  documentsFiltered: (params?: { status?: string; document_type?: string; q?: string; limit?: number; offset?: number }) => {
    const search = buildSearchParams(params)
    return request<Document[]>(`/documents` + search)
  },
  document: (id: number) => request<Document>(`/documents/` + id),
  pages: (id: number) => request<DocumentPage[]>(`/documents/` + id + `/pages`),
  blocks: (id: number) => request<DocumentBlock[]>(`/documents/` + id + `/blocks`),
  entities: (id: number) => request<DocumentEntity[]>(`/documents/` + id + `/entities`),
  documentTimeline: (id: number) => request<DocumentTimelineEvent[]>(`/documents/` + id + `/timeline`),
  ocrRevisions: (pageId: number) => request<OcrRevision[]>(`/documents/pages/` + pageId + `/ocr-revisions`),
  createOcrRevision: (pageId: number, payload: { corrected_text: string; reason?: string | null }) =>
    request<OcrRevision>(`/documents/pages/` + pageId + `/ocr-revisions`, { method: "POST", body: JSON.stringify(payload) }),
  jobs: () => request<Job[]>(`/jobs`),
  jobsFiltered: (params?: { status?: string; document_id?: number; limit?: number; offset?: number }) => {
    const search = buildSearchParams(params)
    return request<Job[]>(`/jobs` + search)
  },
  upload: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return request<{ document: Document; job_id: number | null }>("/documents/upload", {
      method: "POST",
      body: form,
    })
  },
  uploadBatch: (files: File[]) => {
    const form = new FormData()
    files.forEach((file) => form.append("files", file))
    return request<BatchUploadResult>("/documents/upload/batch", {
      method: "POST",
      body: form,
    })
  },
  exportSearchCSV: (query: string, limit = 100) => {
    window.open(`${API_BASE_URL}` + "/search/export/csv?q=" + encodeURIComponent(query) + "&limit=" + limit, "_blank")
  },
  exportSearchJSON: (query: string, limit = 100) => {
    window.open(`${API_BASE_URL}` + "/search/export/json?q=" + encodeURIComponent(query) + "&limit=" + limit, "_blank")
  },
  reprocess: (id: number) => request<Job>(`/documents/` + id + `/reprocess`, { method: "POST" }),
  reprocessOCR: (id: number) => request<Job>(`/documents/` + id + `/reprocess?mode=ocr`, { method: "POST" }),
  reprocessBulk: (payload: { status?: string | null; document_type?: string | null; source_path_contains?: string | null; ids?: number[] | null; limit?: number; mode?: string }) =>
    request<BulkReprocessResponse>("/documents/reprocess-bulk", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  scan: () => request<{ scanned: number; registered: number; duplicates: number; skipped: number }>("/ingestion/scan", { method: "POST" }),
  textSearch: (query: string) => request<SearchResult[]>(`/search/text?q=` + encodeURIComponent(query)),
  guidedSearch: (query: string, mode: string) =>
    request<SearchResult[]>(`/search/guided?mode=` + encodeURIComponent(mode) + `&q=` + encodeURIComponent(query)),
  semanticSearch: (query: string, filters?: Record<string, unknown>) =>
    request<SearchResult[]>("/search/semantic", {
      method: "POST",
      body: JSON.stringify({ query, filters, limit: 20 }),
    }),
  hybridSearch: (query: string, filters?: Record<string, unknown>) =>
    request<SearchResult[]>("/search/hybrid", {
      method: "POST",
      body: JSON.stringify({ query, filters, limit: 20 }),
    }),
  savedSearches: () => request<SavedSearch[]>("/search/saved"),
  createSavedSearch: (payload: { name: string; query: string; mode?: string; filters_json?: Record<string, unknown> }) =>
    request<SavedSearch>("/search/saved", { method: "POST", body: JSON.stringify(payload) }),
  askAI: (question: string, mode?: string) =>
    request<AIAnswer>("/ai/ask", {
      method: "POST",
      body: JSON.stringify({ question, mode }),
    }),
  aiAnswer: (id: number) => request<AIAnswer>(`/ai/answers/` + id),
  aiHistory: () => request<AIQuestion[]>(`/ai/history`),
  budgets: () => request<Budget[]>(`/budgets`),
  budgetLines: (id: number) => request<BudgetLine[]>(`/budgets/` + id + `/lines`),
  acceptedBudgetsWithoutOrder: () => request<Budget[]>(`/budgets/accepted-without-order`),
  orders: () => request<Order[]>(`/orders`),
  orderLines: (id: number) => request<OrderLine[]>(`/orders/` + id + `/lines`),
  invoices: (params?: { q?: string; limit?: number }) => request<Invoice[]>(`/invoices` + buildSearchParams(params)),
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
  generateReconciliationIssues: () => request<ReconciliationIssue[]>(`/reconciliation/issues/generate`, { method: "POST" }),
  updateReconciliationIssue: (id: number, payload: { status?: string; resolution_notes?: string | null }) =>
    request<ReconciliationIssue>(`/reconciliation/issues/` + id, { method: "PATCH", body: JSON.stringify(payload) }),
  plans: () => request<Plan[]>(`/plans`),
  planRooms: (id: number) => request<PlanRoom[]>(`/plans/` + id + `/rooms`),
  planDimensions: (id: number) => request<PlanDimension[]>(`/plans/` + id + `/dimensions`),
  planMeasurements: (id: number) => request<PlanMeasurement[]>(`/plans/` + id + `/measurements`),
  createPlanMeasurement: (id: number, payload: { label: string; page_number?: number | null; measurement_type?: string; value_m?: number | null; ocr_value_m?: number | null; points_json?: Record<string, unknown>[]; calibration_json?: Record<string, unknown> | null }) =>
    request<PlanMeasurement>(`/plans/` + id + `/measurements`, { method: "POST", body: JSON.stringify(payload) }),
  updatePlanScale: (id: number, payload: Partial<Pick<Plan, "scale_text" | "scale_ratio" | "scale_confidence" | "unit" | "has_valid_scale">>) =>
    request<Plan>(`/plans/` + id + `/scale`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  updatePlanRoom: (id: number, payload: Partial<Pick<PlanRoom, "name" | "area_m2" | "width_m" | "length_m" | "confidence" | "source" | "needs_review">>) =>
    request<PlanRoom>(`/plan-rooms/` + id, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  ocrErrors: () => request<Document[]>(`/admin/ocr-errors`),
  duplicates: () => request<Document[]>(`/admin/duplicates`),
  hotelChains: () => request<HotelChain[]>(`/admin/hotel-chains`),
  createHotelChain: (payload: { name: string; is_active?: boolean }) =>
    request<HotelChain>("/admin/hotel-chains", { method: "POST", body: JSON.stringify(payload) }),
  hotels: () => request<Hotel[]>(`/admin/hotels`),
  createHotel: (payload: { chain_id: number; name: string; code?: string | null; is_active?: boolean }) =>
    request<Hotel>("/admin/hotels", { method: "POST", body: JSON.stringify(payload) }),
  folderRules: () => request<FolderRule[]>(`/admin/folder-rules`),
  createFolderRule: (payload: {
    name?: string | null
    pattern: string
    match_type?: string
    chain_id?: number | null
    hotel_id?: number | null
    tags_json?: string[]
    is_active?: boolean
  }) => request<FolderRule>("/admin/folder-rules", { method: "POST", body: JSON.stringify(payload) }),
  applyFolderRules: (force = false) =>
    request<{ matched: number; assigned: number; quarantined: number; skipped: number }>("/admin/folder-rules/apply", {
      method: "POST",
      body: JSON.stringify({ force }),
    }),
  quarantineDocuments: () => request<Document[]>(`/admin/quarantine-documents`),
  updateDocumentAccess: (documentId: number, payload: { chain_id?: number | null; hotel_id?: number | null; assignment_status?: string; tags_json?: string[]; locked_manual?: boolean }) =>
    request(`/admin/document-access/` + documentId, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  accessGroups: () => request<AccessGroup[]>(`/admin/access-groups`),
  createAccessGroup: (payload: { name: string; description?: string | null; permissions_json: Record<string, unknown>; is_active?: boolean }) =>
    request<AccessGroup>("/admin/access-groups", { method: "POST", body: JSON.stringify(payload) }),
  upsertAccessGroupMember: (groupId: number, payload: { principal_type: "user" | "technician"; principal_id: string }) =>
    request<AccessGroupMember>(`/admin/access-groups/` + groupId + `/members`, { method: "POST", body: JSON.stringify(payload) }),
  sensitiveTags: () => request<SensitiveTag[]>(`/admin/sensitive-tags`),
  createSensitiveTag: (payload: { name: string; description?: string | null; is_active?: boolean }) =>
    request<SensitiveTag>("/admin/sensitive-tags", { method: "POST", body: JSON.stringify(payload) }),
}

export function downloadUrl(documentId: number) {
  return `${API_BASE_URL}` + "/documents/" + documentId + "/download"
}

function buildSearchParams(params?: Record<string, unknown>) {
  const search = new URLSearchParams()
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value))
  })
  return search.size ? "?" + search.toString() : ""
}
