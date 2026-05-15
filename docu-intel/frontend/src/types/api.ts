export type User = {
  id: number
  email: string
  name: string
  role: "admin" | "gestor" | "operario" | "auditor"
  is_active: boolean
  created_at: string
}

export type Document = {
  id: number
  original_filename: string
  stored_filename: string | null
  source_path: string | null
  file_hash: string
  mime_type: string | null
  extension: string | null
  file_size: number
  document_type: string
  status: string
  confidence: number | null
  page_count: number | null
  error_message: string | null
  duplicate_of_document_id: number | null
  created_at: string
  processed_at: string | null
}

export type DocumentPage = {
  id: number
  document_id: number
  page_number: number
  width: number | null
  height: number | null
  text: string | null
  image_path: string | null
  ocr_confidence: number | null
  created_at: string
}

export type OcrReviewPage = {
  document_id: number
  original_filename: string
  document_type: string
  status: string
  confidence: number | null
  page_id: number
  page_number: number
  ocr_confidence: number | null
  review_status: "pending" | "approved" | "rejected" | string
  review_notes: string | null
  reviewed_at: string | null
  reviewed_by_id: number | null
  text: string
  text_excerpt: string
  preview_url: string | null
  created_at: string
}

export type DocumentBlock = {
  id: number
  document_id: number
  page_id: number | null
  page_number: number | null
  block_type: string
  text: string | null
  bbox_x1: number | null
  bbox_y1: number | null
  bbox_x2: number | null
  bbox_y2: number | null
  confidence: number | null
  source_engine: string | null
  created_at: string
}

export type DocumentEntity = {
  id: number
  document_id: number
  entity_type: string
  entity_value: string
  normalized_value: string | null
  confidence: number | null
  page_number: number | null
  source_block_id: number | null
  created_at: string
}

export type Job = {
  id: number
  document_id: number
  job_type: string
  status: string
  started_at: string | null
  finished_at: string | null
  error_message: string | null
  retries: number
}

export type AdminStats = {
  documents_total: number
  documents_processed: number
  documents_pending: number
  documents_failed: number
  documents_needs_review: number
  duplicates: number
  ocr_errors: number
  accepted_budgets_without_order: number
  plans_without_valid_scale: number
}

export type AdminAlert = {
  key: string
  title: string
  description: string
  severity: "critical" | "warning" | "info" | string
  count: number
  action_url: string
}

export type ProcessingMetrics = {
  documents_by_status: Record<string, number>
  documents_by_type: Record<string, number>
  jobs_by_status: Record<string, number>
  audit_events_total: number
}

export type DiskUsage = {
  path: string
  total: number
  used: number
  free: number
}

export type OperationsStatus = {
  jobs_by_status: Record<string, number>
  watched_files_by_status: Record<string, number>
  ingestion_events_by_type: Record<string, number>
  disk: {
    input_dir: DiskUsage
    files_dir: DiskUsage
  }
}

export type MaintenanceReport = {
  checks: { key: string; status: string; count: number }[]
  disk: {
    input_dir: DiskUsage
    files_dir: DiskUsage
  }
}

export type WatchedFile = {
  id: number
  path: string
  status: string
  size_bytes: number | null
  mtime_epoch: number | null
  document_id: number | null
  job_id: number | null
  error_message: string | null
  first_seen_at: string
  last_seen_at: string
  updated_at: string
}

export type IngestionEvent = {
  id: number
  event_type: string
  source_path: string | null
  document_id: number | null
  job_id: number | null
  watched_file_id: number | null
  details_json: Record<string, unknown> | null
  error_message: string | null
  created_at: string
}

export type AccessExplain = {
  allowed: boolean
  reasons: string[]
  scope: Record<string, unknown>
}

export type DocumentGraph = {
  nodes: { document_id: number; filename: string; document_type: string; status: string }[]
  edges: { from_document_id: number; to_document_id: number; relation: string; label?: string | null }[]
}

export type AuditLog = {
  id: number
  user_id: number | null
  action: string
  entity_type: string | null
  entity_id: number | null
  details_json: Record<string, unknown> | null
  created_at: string
}

export type BulkReprocessResponse = {
  matched: number
  enqueued: number
  skipped: number
  job_ids: number[]
  mode: string
}

export type SearchResult = {
  document_id: number
  original_filename: string
  document_type: string
  status: string
  page_number: number | null
  block_id: number | null
  score: number
  excerpt: string
  ocr_confidence: number | null
  source_type: string
}

export type AIAnswerSource = {
  id: number
  answer_id: number
  document_id: number | null
  page_number: number | null
  block_id: number | null
  relevance_score: number | null
  excerpt: string | null
}

export type AIAnswer = {
  id: number
  question_id: number
  answer: string
  confidence: number | null
  model_name: string | null
  created_at: string
  sources: AIAnswerSource[]
}

export type Budget = {
  id: number
  document_id: number
  budget_number: string | null
  client_name: string | null
  date: string | null
  total_amount: number | null
  currency: string | null
  status: string | null
  accepted_detected: boolean
  confidence: number | null
  created_at: string
}

export type BudgetLine = {
  id: number
  budget_id: number
  reference: string | null
  description: string | null
  quantity: number | null
  unit: string | null
  unit_price: number | null
  total_price: number | null
  confidence: number | null
}

export type Order = {
  id: number
  document_id: number
  order_number: string | null
  supplier_name: string | null
  client_name: string | null
  date: string | null
  total_amount: number | null
  currency: string | null
  related_budget_id: number | null
  confidence: number | null
  created_at: string
}

export type OrderLine = {
  id: number
  order_id: number
  reference: string | null
  description: string | null
  quantity: number | null
  unit: string | null
  unit_price: number | null
  total_price: number | null
  confidence: number | null
}

export type Plan = {
  id: number
  document_id: number
  project_name: string | null
  scale_text: string | null
  scale_ratio: number | null
  scale_confidence: number | null
  unit: string | null
  has_valid_scale: boolean
  created_at: string
}

export type PlanRoom = {
  id: number
  plan_id: number
  name: string | null
  area_m2: number | null
  width_m: number | null
  length_m: number | null
  polygon_json: Record<string, unknown> | null
  confidence: number | null
  source: string | null
  needs_review: boolean
}

export type PlanDimension = {
  id: number
  plan_id: number
  raw_text: string | null
  value: number | null
  unit: string | null
  value_m: number | null
  page_number: number | null
  bbox_x1: number | null
  bbox_y1: number | null
  bbox_x2: number | null
  bbox_y2: number | null
  confidence: number | null
}

export type HotelChain = {
  id: number
  name: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export type Hotel = {
  id: number
  chain_id: number
  name: string
  code: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type FolderRule = {
  id: number
  name: string | null
  pattern: string
  match_type: string
  chain_id: number | null
  hotel_id: number | null
  tags_json: string[]
  is_active: boolean
  created_at: string
  updated_at: string
}

export type DocumentAccess = {
  document_id: number
  chain_id: number | null
  hotel_id: number | null
  assignment_status: string
  assignment_source: string
  tags_json: string[]
  locked_manual: boolean
  updated_at: string
}

export type AccessGroup = {
  id: number
  name: string
  description: string | null
  permissions_json: Record<string, unknown>
  is_active: boolean
  created_at: string
  updated_at: string
}

export type AccessGroupMember = {
  id: number
  group_id: number
  principal_type: "user" | "technician"
  principal_id: string
  created_at: string
}

export type SensitiveTag = {
  id: number
  name: string
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}
