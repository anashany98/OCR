/**
 * useAdminOperationalData - queries and state for the
 * ``/admin/operativa`` tab.
 *
 * Extracted from the old ``useAdminData`` megahook (F4b) so this
 * tab fetches only its own data. The bulk-reprocess confirm dialog
 * is shared with the shell via ``useAdminReprocess``.
 */
import { useId, useRef, useState, useEffect, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

import { AdminReprocessContext } from "./useAdminReprocess"

export function useAdminOperationalData() {
  const queryClient = useQueryClient()

  // Local state for the operational tab forms and the reprocess
  // dialog state. These used to live in the global ``useAdminData``
  // hook, which is why they were shared across tabs even though
  // only this tab uses them.
  const [status, setStatus] = useState("failed")
  const [documentType, setDocumentType] = useState("")
  const [sourcePath, setSourcePath] = useState("")
  const [mode, setMode] = useState("full")
  const [graphDocumentId, setGraphDocumentId] = useState("")
  const [reprocessConfirmOpen, setReprocessConfirmOpen] = useState(false)

  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats })
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts })
  const metrics = useQuery({ queryKey: ["processing-metrics"], queryFn: api.processingMetrics })
  const queueStatus = useQuery({
    queryKey: ["queues"],
    queryFn: api.queues,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  })
  const operationsOverview = useQuery({
    queryKey: ["operations-overview"],
    queryFn: api.operationsOverview,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  })
  const operationsStatus = useQuery({
    queryKey: ["operations-status"],
    queryFn: api.operationsStatus,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  })
  const maintenanceReport = useQuery({
    queryKey: ["maintenance-report"],
    queryFn: api.maintenanceReport,
    refetchInterval: 15000,
    refetchIntervalInBackground: false,
  })
  const operationsDocuments = useQuery({
    queryKey: ["operations-documents"],
    queryFn: () => api.operationsDocuments({ limit: 10 }),
    refetchInterval: 15000,
    refetchIntervalInBackground: false,
  })
  const watchedFiles = useQuery({
    queryKey: ["watched-files"],
    queryFn: api.watchedFiles,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  })
  const ingestionEvents = useQuery({
    queryKey: ["ingestion-events"],
    queryFn: api.ingestionEvents,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  })
  const auditLogs = useQuery({ queryKey: ["audit-logs"], queryFn: api.auditLogs })

  const pauseQueues = useMutation({
    mutationFn: api.pauseQueues,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["queues"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const resumeQueues = useMutation({
    mutationFn: api.resumeQueues,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["queues"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const loadDocumentGraph = useMutation({
    mutationFn: () => api.documentGraph(Number(graphDocumentId)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })

  // The reprocess mutation is shared with the shell (which owns the
  // confirm dialog) and lives in ``useAdminReprocess``. We just
  // publish the filter state into the context.
  const reprocessContextValue = {
    status,
    setStatus,
    documentType,
    setDocumentType,
    sourcePath,
    setSourcePath,
    mode,
    setMode,
    reprocessConfirmOpen,
    setReprocessConfirmOpen,
  }

  function onReprocessSubmit(event: FormEvent) {
    event.preventDefault()
    setReprocessConfirmOpen(true)
  }

  return {
    state: {
      status,
      setStatus,
      documentType,
      setDocumentType,
      sourcePath,
      setSourcePath,
      mode,
      setMode,
      graphDocumentId,
      setGraphDocumentId,
      reprocessConfirmOpen,
      setReprocessConfirmOpen,
    },
    queries: {
      stats,
      alerts,
      metrics,
      queueStatus,
      operationsOverview,
      operationsStatus,
      maintenanceReport,
      operationsDocuments,
      watchedFiles,
      ingestionEvents,
      auditLogs,
    },
    mutations: {
      pauseQueues,
      resumeQueues,
      loadDocumentGraph,
    },
    handlers: { onReprocessSubmit },
    reprocessContextValue,
    AdminReprocessContext,
  }
}

export type AdminOperationalData = ReturnType<typeof useAdminOperationalData>

/**
 * Modal used by the operational tab to confirm a bulk reprocess.
 * Lives next to the hook because the shell renders it independently
 * of which tab is active.
 */
export function AdminReprocessConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  confirmDisabled = false,
  onCancel,
  onConfirm,
}: {
  open: boolean
  title: string
  description: string
  confirmLabel: string
  confirmDisabled?: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const titleId = useId()
  const descriptionId = useId()
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus()

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault()
        onCancel()
      }
    }

    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <button
        type="button"
        aria-label="Cancelar acción"
        className="absolute inset-0 bg-black/45"
        onClick={onCancel}
        tabIndex={-1}
      />
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className="relative w-full max-w-md rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-xl"
      >
        <h2 id={titleId} className="text-base font-semibold text-[var(--text-primary)]">
          {title}
        </h2>
        <p id={descriptionId} className="mt-2 text-sm text-[var(--text-secondary)]">
          {description}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded-md border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm font-medium hover:bg-[var(--bg-elevated)]"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={confirmDisabled}
            className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-50"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
