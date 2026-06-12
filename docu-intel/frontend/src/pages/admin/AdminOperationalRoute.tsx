import { AdminOperationalTab } from "./AdminOperationalTab"
import { useAdminOperationalData } from "./useAdminOperationalData"
import { useAdminReprocess } from "./useAdminReprocess"

/**
 * F4b - Operational admin sub-route. Lazy-loaded via the router.
 *
 * Mounts ``useAdminOperationalData`` so this tab fetches only its
 * own queries. The bulk-reprocess filters are kept in local state
 * here (not in the megahook) and published into
 * ``AdminReprocessContext`` so the shell's confirm dialog can read
 * them. The shared ``reprocess`` mutation comes from
 * ``useAdminReprocess``.
 */
export function AdminOperationalRoute() {
  const { state, queries, mutations, handlers, reprocessContextValue, AdminReprocessContext } =
    useAdminOperationalData()
  const { reprocess } = useAdminReprocess()

  return (
    <AdminReprocessContext.Provider value={reprocessContextValue}>
      <AdminOperationalTab
        auditLogs={queries.auditLogs.data ?? []}
        alerts={queries.alerts.data ?? []}
        metrics={queries.metrics.data}
        queueStatus={queries.queueStatus.data}
        operationsOverview={queries.operationsOverview.data}
        operationsStatus={queries.operationsStatus.data}
        maintenanceReport={queries.maintenanceReport.data}
        operationsDocuments={queries.operationsDocuments.data}
        watchedFiles={queries.watchedFiles.data ?? []}
        ingestionEvents={queries.ingestionEvents.data ?? []}
        stats={queries.stats.data}
        status={state.status}
        setStatus={state.setStatus}
        documentType={state.documentType}
        setDocumentType={state.setDocumentType}
        sourcePath={state.sourcePath}
        setSourcePath={state.setSourcePath}
        mode={state.mode}
        setMode={state.setMode}
        reprocessPending={reprocess.isPending}
        reprocessResult={reprocess.data}
        reprocessError={reprocess.isError ? (reprocess.error as Error).message : null}
        onReprocessSubmit={handlers.onReprocessSubmit}
        pauseQueues={{
          mutate: () => mutations.pauseQueues.mutate(),
          isPending: mutations.pauseQueues.isPending,
          data: mutations.pauseQueues.data,
          isError: mutations.pauseQueues.isError,
          error: mutations.pauseQueues.error,
        }}
        resumeQueues={{
          mutate: () => mutations.resumeQueues.mutate(),
          isPending: mutations.resumeQueues.isPending,
          data: mutations.resumeQueues.data,
          isError: mutations.resumeQueues.isError,
          error: mutations.resumeQueues.error,
        }}
        graphDocumentId={state.graphDocumentId}
        setGraphDocumentId={state.setGraphDocumentId}
        loadDocumentGraph={{
          mutate: () => mutations.loadDocumentGraph.mutate(),
          isPending: mutations.loadDocumentGraph.isPending,
          data: mutations.loadDocumentGraph.data,
          isError: mutations.loadDocumentGraph.isError,
          error: mutations.loadDocumentGraph.error,
        }}
      />
    </AdminReprocessContext.Provider>
  )
}
