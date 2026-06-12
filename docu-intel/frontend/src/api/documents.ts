import type {
  BulkReprocessResponse,
  Document,
  DocumentBlock,
  DocumentEntity,
  DocumentPage,
  DocumentTimelineEvent,
  Job,
  OcrRevision,
} from "@/types/api"
import { BatchUploadResult, buildSearchParams, request } from "./core"

export const documentsApi = {
  documents: () => request<Document[]>("/documents"),
  documentsFiltered: (params?: {
    status?: string
    document_type?: string
    q?: string
    limit?: number
    offset?: number
  }) => {
    const search = buildSearchParams(params)
    return request<Document[]>(`/documents` + search)
  },
  document: (id: number) => request<Document>(`/documents/` + id),
  pages: (id: number) => request<DocumentPage[]>(`/documents/` + id + `/pages`),
  blocks: (id: number) => request<DocumentBlock[]>(`/documents/` + id + `/blocks`),
  entities: (id: number) => request<DocumentEntity[]>(`/documents/` + id + `/entities`),
  documentTimeline: (id: number) =>
    request<DocumentTimelineEvent[]>(`/documents/` + id + `/timeline`),
  ocrRevisions: (pageId: number) =>
    request<OcrRevision[]>(`/documents/pages/` + pageId + `/ocr-revisions`),
  createOcrRevision: (
    pageId: number,
    payload: { corrected_text: string; reason?: string | null },
  ) =>
    request<OcrRevision>(`/documents/pages/` + pageId + `/ocr-revisions`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  jobs: () => request<Job[]>(`/jobs`),
  jobsFiltered: (params?: {
    status?: string
    document_id?: number
    limit?: number
    offset?: number
  }) => {
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
  uploadBatch: (files: File[], relativePaths?: string[]) => {
    const form = new FormData()
    files.forEach((file) => form.append("files", file))
    if (relativePaths && relativePaths.length) {
      form.append("relative_paths", JSON.stringify(relativePaths))
    }
    return request<BatchUploadResult>("/documents/upload/batch", {
      method: "POST",
      body: form,
    })
  },
  reprocess: (id: number) => request<Job>(`/documents/` + id + `/reprocess`, { method: "POST" }),
  reprocessOCR: (id: number) =>
    request<Job>(`/documents/` + id + `/reprocess?mode=ocr`, { method: "POST" }),
  reprocessBulk: (payload: {
    status?: string | null
    document_type?: string | null
    source_path_contains?: string | null
    ids?: number[] | null
    limit?: number
    mode?: string
  }) =>
    request<BulkReprocessResponse>("/documents/reprocess-bulk", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  scan: () =>
    request<{ scanned: number; registered: number; duplicates: number; skipped: number }>(
      "/ingestion/scan",
      { method: "POST" },
    ),
}
