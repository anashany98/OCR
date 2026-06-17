import type {
  OcrCascadeAttempt,
  OcrFlowDocumentStep,
  OcrFlowLiveJob,
} from "@/types/api"

import { API_BASE_URL } from "./core"
import { request } from "./core"

interface OcrFlowLiveResponse {
  jobs: OcrFlowLiveJob[]
}

interface OcrFlowDocumentResponse {
  document_id: number
  original_filename: string
  status: string
  steps: OcrFlowDocumentStep[]
}

export const ocrFlowApi = {
  live: () => request<OcrFlowLiveResponse>("/admin/ocr-flow/live"),
  documentFlow: (documentId: number) =>
    request<OcrFlowDocumentResponse>(`/documents/${documentId}/flow`),
}

/**
 * Build the URL for the SSE stream.
 *
 * The ``EventSource`` browser API cannot send custom ``Authorization``
 * headers, so the backend also accepts the bearer token as
 * ``?token=…``. The caller is responsible for reading the token
 * from the auth store and passing it here.
 */
export function ocrFlowStreamUrl(token: string | null) {
  const base = `${API_BASE_URL}/admin/ocr-flow/stream`
  if (!token) return base
  return `${base}?token=${encodeURIComponent(token)}`
}

export type { OcrCascadeAttempt, OcrFlowDocumentStep, OcrFlowLiveJob }
