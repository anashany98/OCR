import { AdminQualityTab } from "./AdminQualityTab"
import { useAdminQualityData } from "./useAdminQualityData"

/**
 * F4b - Quality admin sub-route. Lazy-loaded via the router.
 */
export function AdminQualityRoute() {
  const { state, queries, mutations, tenantAdminEnabled } = useAdminQualityData()

  return (
    <AdminQualityTab
      qualityRules={queries.qualityRules.data}
      qualitySummary={queries.qualitySummary.data}
      recalculateQuality={{
        mutate: () => mutations.recalculateQuality.mutate(),
        isPending: mutations.recalculateQuality.isPending,
        data: mutations.recalculateQuality.data,
        isError: mutations.recalculateQuality.isError,
        error: mutations.recalculateQuality.error,
      }}
      ocrReviewPages={queries.ocrReview.data ?? []}
      duplicates={queries.duplicates.data ?? []}
      quarantine={queries.quarantine.data ?? []}
      tenantAdminEnabled={tenantAdminEnabled}
      bulkTagDocumentIds={state.bulkTagDocumentIds}
      setBulkTagDocumentIds={state.setBulkTagDocumentIds}
      bulkTagAdd={state.bulkTagAdd}
      setBulkTagAdd={state.setBulkTagAdd}
      bulkTagRemove={state.bulkTagRemove}
      setBulkTagRemove={state.setBulkTagRemove}
      applyBulkTags={{
        mutate: () => mutations.applyBulkTags.mutate(),
        isPending: mutations.applyBulkTags.isPending,
        data: mutations.applyBulkTags.data,
        isError: mutations.applyBulkTags.isError,
        error: mutations.applyBulkTags.error,
      }}
      assignDocumentId={state.assignDocumentId}
      setAssignDocumentId={state.setAssignDocumentId}
      assignChainId={state.assignChainId}
      setAssignChainId={state.setAssignChainId}
      assignHotelId={state.assignHotelId}
      setAssignHotelId={state.setAssignHotelId}
      assignTags={state.assignTags}
      setAssignTags={state.setAssignTags}
      chains={queries.chains.data ?? []}
      hotels={queries.hotels.data ?? []}
      updateDocumentAccess={{
        mutate: () => mutations.updateDocumentAccess.mutate(),
        isPending: mutations.updateDocumentAccess.isPending,
        data: mutations.updateDocumentAccess.data,
        isError: mutations.updateDocumentAccess.isError,
        error: mutations.updateDocumentAccess.error,
      }}
    />
  )
}
