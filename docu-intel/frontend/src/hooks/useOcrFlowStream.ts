import { useEffect } from "react"
import { useQueryClient } from "@tanstack/react-query"

import type { OcrFlowLiveJob } from "@/types/api"

import { ocrFlowStreamUrl } from "@/api/client"

export const OCR_FLOW_LIVE_KEY = ["ocr-flow", "live"] as const

export interface OcrFlowLiveSnapshot {
  jobs: OcrFlowLiveJob[]
}

export interface OcrFlowEvent {
  type: string
  task?: string
  task_id?: string
  document_id?: number
  state?: string
  error?: string
  runtime_s?: number
}

/**
 * Pure reducer-style helper exposed for unit tests.
 *
 * Returns a *new* snapshot so React Query's referential equality check
 * picks the change up and re-renders subscribers.
 */
export function mergeOcrFlowEvent(
  snapshot: OcrFlowLiveSnapshot,
  event: OcrFlowEvent,
): OcrFlowLiveSnapshot {
  if (event.type === "job.finished" || event.type === "job.failed") {
    return {
      jobs: snapshot.jobs.filter(
        (job) => job.document_id !== event.document_id,
      ),
    }
  }
  if (event.type === "job.started" || event.type === "job.queued") {
    const placeholder: OcrFlowLiveJob = {
      job_id: 0,
      document_id: event.document_id ?? 0,
      original_filename: "(iniciando…)",
      job_type: event.task?.split(".").pop() ?? "extract",
      status: event.type === "job.queued" ? "pending" : "started",
      started_at: new Date().toISOString(),
      retries: 0,
      error: null,
    }
    return {
      jobs: [
        placeholder,
        ...snapshot.jobs.filter(
          (job) => job.document_id !== placeholder.document_id,
        ),
      ],
    }
  }
  return snapshot
}

/**
 * Subscribe to the OCR flow SSE stream and push every event into the
 * TanStack Query cache. The browser auto-reconnects on drop; we just
 * wire messages to ``setQueryData``.
 */
export function useOcrFlowStream() {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      return
    }
    const source = new EventSource(ocrFlowStreamUrl(null), {
      withCredentials: true,
    })
    const handler = (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data) as OcrFlowEvent
        queryClient.setQueryData<OcrFlowLiveSnapshot>(
          OCR_FLOW_LIVE_KEY,
          (prev) => mergeOcrFlowEvent(prev ?? { jobs: [] }, parsed),
        )
      } catch {
        // ignore malformed events
      }
    }
    source.onmessage = handler
    source.onerror = () => {
      // The browser will auto-reconnect; nothing to do.
    }
    return () => {
      source.close()
    }
  }, [queryClient])
}
