import { useOutletContext } from "react-router-dom"

import { AdminOperationalTab } from "./AdminOperationalTab"
import type { AdminData } from "./useAdminData"

/**
 * F4b - Operational admin sub-route. Lazy-loaded via the router.
 *
 * Wraps the existing ``AdminOperationalTab`` (a controlled
 * component that takes its data via props) with the data hook the
 * shell exposes through ``<Outlet context={data} />``.
 */
export function AdminOperationalRoute() {
  const data = useOutletContext<AdminData>()
  const { state, queries, mutations, handlers } = data

  return (
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
      reprocessPending={mutations.reprocess.isPending}
      reprocessResult={mutations.reprocess.data}
      reprocessError={mutations.reprocess.isError ? mutations.reprocess.error.message : null}
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
  )
}
