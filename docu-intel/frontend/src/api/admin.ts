import type {
  AccessExplain,
  AccessGroup,
  AccessGroupMember,
  AdminAlert,
  AdminStats,
  AdminUser,
  AuditLog,
  BulkReprocessResponse,
  BulkTagsResponse,
  Document,
  DocumentGraph,
  EffectiveAccess,
  FolderRule,
  Hotel,
  HotelChain,
  IngestionEvent,
  Job,
  MaintenanceReport,
  NotificationRule,
  OcrReviewPage,
  OperationsOverview,
  OperationsStatus,
  PaginatedDocuments,
  ProcessingMetrics,
  ProductionChecklist,
  ProductionReadiness,
  QualityRecalculateResponse,
  QualityRules,
  QualitySummary,
  QueueStatus,
  RedactionPreview,
  RulePreview,
  SavedView,
  SensitiveTag,
  StorageIntegrity,
  SystemHealth,
  WatchedFile,
  WorkInboxActionResponse,
  WorkInboxItem,
  WorkItem,
  WorkItemComment,
} from "@/types/api"
import { buildSearchParams, request } from "./core"

export const adminApi = {
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
  ocrReview: (params?: { max_confidence?: number; limit?: number; document_type?: string; status?: string; review_status?: string }) =>
    request<OcrReviewPage[]>("/admin/ocr-review" + buildSearchParams(params)),
  updateOcrReview: (pageId: number, payload: { review_status: "pending" | "approved" | "rejected"; review_notes?: string | null }) =>
    request<OcrReviewPage>("/admin/ocr-review/" + pageId, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  reprocessOcrPage: (pageId: number) => request<Job>("/admin/quality/pages/" + pageId + "/reprocess-ocr", { method: "POST" }),
  reembedDocument: (documentId: number) =>
    request<{
      document_id: number
      chunks_updated: number
      chunks_with_embedding: number
      chunks_needing_reembedding: number
      provider: string
    }>("/admin/documents/" + documentId + "/re-embed", { method: "POST" }),
  documentsNeedingReembedding: (params: { limit?: number } = {}) =>
    request<Array<{
      document_id: number
      original_filename: string
      document_type: string | null
      status: string
      created_at: string
      chunks_total: number
      chunks_needing_reembedding: number
    }>>("/admin/documents/needs-re-embedding" + (params.limit ? "?limit=" + params.limit : "")),
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
