import type {
  AdminAlert,
  AdminStats,
  AccessGroup,
  AccessGroupMember,
  AccessExplain,
  AIAnswer,
  AuditLog,
  Budget,
  BudgetLine,
  BulkReprocessResponse,
  Document,
  DocumentBlock,
  DocumentEntity,
  DocumentGraph,
  DocumentPage,
  FolderRule,
  Hotel,
  HotelChain,
  IngestionEvent,
  Job,
  MaintenanceReport,
  OcrReviewPage,
  Order,
  OrderLine,
  OperationsStatus,
  Plan,
  PlanDimension,
  PlanRoom,
  ProcessingMetrics,
  SearchResult,
  SensitiveTag,
  User,
  WatchedFile,
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
  operationsStatus: () => request<OperationsStatus>("/admin/operations-status"),
  maintenanceReport: () => request<MaintenanceReport>("/admin/maintenance-report"),
  watchedFiles: () => request<WatchedFile[]>("/admin/watched-files?limit=50"),
  ingestionEvents: () => request<IngestionEvent[]>("/admin/ingestion-events?limit=50"),
  accessExplain: (params: { principal_type: "user" | "technician"; principal_id: string; document_id: number }) =>
    request<AccessExplain>("/admin/access-explain" + buildSearchParams(params)),
  documentGraph: (documentId: number) => request<DocumentGraph>("/admin/documents/" + documentId + "/graph"),
  auditLogs: () => request<AuditLog[]>("/admin/audit-logs"),
  ocrReview: (params?: { max_confidence?: number; limit?: number }) =>
    request<OcrReviewPage[]>("/admin/ocr-review" + buildSearchParams(params)),
  updateOcrReview: (pageId: number, payload: { review_status: "pending" | "approved" | "rejected"; review_notes?: string | null }) =>
    request<OcrReviewPage>("/admin/ocr-review/" + pageId, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  documents: () => request<Document[]>("/documents"),
  documentsFiltered: (params?: { status?: string; document_type?: string; q?: string; limit?: number; offset?: number }) => {
    const search = buildSearchParams(params)
    return request<Document[]>(`/documents` + search)
  },
  document: (id: number) => request<Document>(`/documents/` + id),
  pages: (id: number) => request<DocumentPage[]>(`/documents/` + id + `/pages`),
  blocks: (id: number) => request<DocumentBlock[]>(`/documents/` + id + `/blocks`),
  entities: (id: number) => request<DocumentEntity[]>(`/documents/` + id + `/entities`),
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
  askAI: (question: string, mode?: string) =>
    request<AIAnswer>("/ai/ask", {
      method: "POST",
      body: JSON.stringify({ question, mode }),
    }),
  aiAnswer: (id: number) => request<AIAnswer>(`/ai/answers/` + id),
  budgets: () => request<Budget[]>(`/budgets`),
  budgetLines: (id: number) => request<BudgetLine[]>(`/budgets/` + id + `/lines`),
  acceptedBudgetsWithoutOrder: () => request<Budget[]>(`/budgets/accepted-without-order`),
  orders: () => request<Order[]>(`/orders`),
  orderLines: (id: number) => request<OrderLine[]>(`/orders/` + id + `/lines`),
  plans: () => request<Plan[]>(`/plans`),
  planRooms: (id: number) => request<PlanRoom[]>(`/plans/` + id + `/rooms`),
  planDimensions: (id: number) => request<PlanDimension[]>(`/plans/` + id + `/dimensions`),
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
