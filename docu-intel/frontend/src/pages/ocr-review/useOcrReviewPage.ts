import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"
import { notify } from "@/lib/toast"
import type { OcrReviewPage as OcrReviewPageType } from "@/types/api"

/**
 * F8 - OCR review page data + state hook.
 *
 * The original ``OcrReviewPage`` mixed 30+ lines of query wiring
 * (review queue, needs-reembedding poll, three mutations) with the
 * layout markup. This hook owns the data side so the page can focus
 * on rendering and the four extracted section components
 * (``NeedsReembeddingCard``, ``OcrReviewFilters``,
 * ``OcrReviewQueue``, ``OcrPageDetails``) can stay purely
 * declarative.
 *
 * The hook is the single source of truth for the four state
 * slots the page needs:
 * - ``thresholdPercent`` / ``threshold`` — the OCR confidence
 *   cutoff (a number string the user types and the parsed float
 *   the query consumes).
 * - ``documentType`` / ``statusFilter`` — extra filters shown in
 *   the toolbar.
 * - ``selectedKey`` — the page currently being inspected in the
 *   right-hand detail panel. Re-derived from the review list so
 *   it never points at a stale item.
 * - ``reviewNotes`` — the textarea content for the approve/deny
 *   form. Re-seeded when the user picks a different page.
 */
export function useOcrReviewPage() {
  const queryClient = useQueryClient()
  const [thresholdPercent, setThresholdPercent] = useState("70")
  const [documentType, setDocumentType] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [reviewNotes, setReviewNotes] = useState("")

  const threshold = useMemo(() => {
    const numeric = Number(thresholdPercent)
    if (!Number.isFinite(numeric)) return 0.7
    return Math.min(Math.max(numeric, 0), 100) / 100
  }, [thresholdPercent])

  const reviewQuery = useQuery({
    queryKey: ["ocr-review", threshold, documentType, statusFilter],
    queryFn: () =>
      api.ocrReview({
        max_confidence: threshold,
        document_type: documentType || undefined,
        status: statusFilter || undefined,
        limit: 200,
      }),
  })
  const reviewItems = reviewQuery.data ?? []
  const selected =
    reviewItems.find((item) => reviewKey(item) === selectedKey) ?? reviewItems[0] ?? null

  // Re-seed the notes textarea when the user picks a different
  // page. Using ``page_id`` (instead of the whole ``selected``
  // object) avoids a feedback loop where typing in the textarea
  // would re-fire the effect and clobber the user's input.
  useEffect(() => {
    setReviewNotes(selected?.review_notes ?? "")
  }, [selected?.page_id, selected?.review_notes])

  const reprocess = useMutation({
    mutationFn: (pageId: number) => api.reprocessOcrPage(pageId),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["ocr-review"] })
      queryClient.invalidateQueries({ queryKey: ["jobs"] })
      queryClient.invalidateQueries({ queryKey: ["stats"] })
      notify.success(`Reprocesamiento OCR encolado`, `Job #${job.id} creado.`)
    },
    onError: (err) => notify.error(err, "No se pudo reprocesar la página"),
  })

  const reviewMutation = useMutation({
    mutationFn: ({
      pageId,
      reviewStatus,
      notes,
    }: {
      pageId: number
      reviewStatus: "approved" | "rejected"
      notes?: string
    }) =>
      api.updateOcrReview(pageId, {
        review_status: reviewStatus,
        review_notes: notes || null,
      }),
    onSuccess: (_, vars) => {
      setReviewNotes("")
      queryClient.invalidateQueries({ queryKey: ["ocr-review"] })
      queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
      queryClient.invalidateQueries({ queryKey: ["stats"] })
      const label = vars.reviewStatus === "approved" ? "aprobada" : "denegada"
      notify.success(`Página ${label}`)
    },
    onError: (err) => notify.error(err, "No se pudo registrar la revisión"),
  })

  const reembed = useMutation({
    mutationFn: (documentId: number) => api.reembedDocument(documentId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["ocr-review"] })
      queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
      queryClient.invalidateQueries({ queryKey: ["stats"] })
      queryClient.invalidateQueries({ queryKey: ["documents"] })
      queryClient.invalidateQueries({ queryKey: ["needs-reembedding"] })
      const embedded = result.chunks_with_embedding
      const pending = result.chunks_needing_reembedding
      if (pending === 0) {
        notify.success(
          `Re-embedding completado`,
          `${embedded} chunks re-embedidos con ${result.provider}.`,
        )
      } else {
        notify.warning(
          `Re-embedding parcial`,
          `${embedded} chunks con embedding, ${pending} aún pendientes. Revisa el provider.`,
        )
      }
    },
    onError: (err) => notify.error(err, "No se pudo re-embebir el documento"),
  })

  const needsReembeddingQuery = useQuery({
    queryKey: ["needs-reembedding"],
    queryFn: () => api.documentsNeedingReembedding({ limit: 50 }),
    refetchInterval: 30_000,
  })

  return {
    state: {
      thresholdPercent,
      setThresholdPercent,
      threshold,
      documentType,
      setDocumentType,
      statusFilter,
      setStatusFilter,
      selectedKey,
      setSelectedKey,
      reviewNotes,
      setReviewNotes,
    },
    queries: {
      review: reviewQuery,
      needsReembedding: needsReembeddingQuery,
    },
    data: {
      reviewItems,
      needsReembedding: needsReembeddingQuery.data ?? [],
      selected,
    },
    mutations: {
      reprocess,
      review: reviewMutation,
      reembed,
    },
  }
}

export type OcrReviewData = ReturnType<typeof useOcrReviewPage>

export function reviewKey(item: OcrReviewPageType) {
  return item.document_id + ":" + item.page_number
}
