/**
 * Resolves the ``plan_id`` associated with a document id.
 *
 * The plans API exposes a flat ``GET /plans?limit=...`` list (one row per
 * detected plan). Both ``PlanoAnnotationPage`` and this hook resolve the
 * plan for a given document by filtering that list on ``document_id``.
 * Centralising the lookup here means callers that only need the id
 * (e.g. ``PlanOverlayPreview``) do not have to pull in the heavyweight
 * ``usePlanAnnotation`` hook (which also owns canvas interaction state).
 */
import { useQuery } from "@tanstack/react-query"

import { plansApi } from "@/api/plans"
import { queryKeys } from "@/lib/queryKeys"

export function usePlanForDocument(documentId: number | null | undefined) {
  const valid = documentId != null && Number.isFinite(documentId)
  const query = useQuery({
    queryKey: queryKeys.plans.list(),
    queryFn: () => plansApi.list(200),
    // Plans rarely change while the user is on a single document page;
    // a 60s stale window avoids re-fetching the full list on every render
    // of the preview. Mirrors ``usePlanAnnotation``.
    staleTime: 60_000,
    enabled: valid,
  })

  const plan = query.data?.find((p) => p.document_id === documentId)
  return {
    plan,
    planId: plan?.id ?? null,
    isLoading: valid ? query.isLoading : false,
  }
}
