import { useQuery } from "@tanstack/react-query"

import { ocrFlowApi } from "@/api/ocrFlow"
import {
  OCR_FLOW_LIVE_KEY,
  useOcrFlowStream,
} from "@/hooks/useOcrFlowStream"

export function ocrFlowLiveQueryKey() {
  return OCR_FLOW_LIVE_KEY
}

export function ocrFlowDocumentQueryKey(documentId: number | null) {
  return ["ocr-flow", "document", documentId] as const
}

/**
 * Live snapshot of active OCR jobs. The SSE hook is mounted as a
 * side-effect so the cache is updated in real time. The
 * ``refetchInterval`` is a safety net: if the SSE connection drops
 * the browser will auto-reconnect, but we also re-fetch every 10
 * seconds so the UI does not freeze on stale data.
 */
export function useOcrFlowLive() {
  useOcrFlowStream()
  return useQuery({
    queryKey: ocrFlowLiveQueryKey(),
    queryFn: () => ocrFlowApi.live(),
    refetchInterval: 10_000,
    refetchOnWindowFocus: false,
  })
}

export function useOcrFlowDocument(documentId: number | null) {
  return useQuery({
    queryKey: ocrFlowDocumentQueryKey(documentId),
    queryFn: () => ocrFlowApi.documentFlow(documentId as number),
    enabled: documentId !== null,
  })
}
