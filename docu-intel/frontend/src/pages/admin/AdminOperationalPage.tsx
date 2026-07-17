import {
  AlertsSection,
  AuditRelationsSection,
  BulkReprocessSection,
  IngestionControlSection,
  OperationsCenterSection,
  ProblemDocumentsSection,
} from "./operational-sections"
import { useAdminOperationalData } from "./useAdminOperationalData"
import { useAdminReprocess } from "./useAdminReprocess"

export function AdminOperationalPage() {
  const { state, queries, mutations, handlers, reprocessContextValue, AdminReprocessContext } =
    useAdminOperationalData()
  const { reprocess } = useAdminReprocess()

  return (
    <AdminReprocessContext.Provider value={reprocessContextValue}>
      <div className="space-y-6">
        <AlertsSection alerts={queries.alerts.data ?? []} />
        <IngestionControlSection
          queueStatus={queries.queueStatus.data}
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
        />
        <OperationsCenterSection
          operationsOverview={queries.operationsOverview.data}
          operationsStatus={queries.operationsStatus.data}
        />
        <BulkReprocessSection
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
        />
        <ProblemDocumentsSection
          operationsDocuments={queries.operationsDocuments.data}
          ingestionEvents={queries.ingestionEvents.data ?? []}
        />
        <AuditRelationsSection
          auditLogs={queries.auditLogs.data ?? []}
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
      </div>
    </AdminReprocessContext.Provider>
  )
}
