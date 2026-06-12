/**
 * useAdminReprocess - shared admin data for the bulk-reprocess confirm
 * dialog owned by the admin shell.
 *
 * The reprocess mutation touches a cross-cutting piece of UI (the
 * confirm dialog lives in ``AdminPage`` and is rendered regardless of
 * the active tab), so the shell and the operational tab both need
 * access to the same ``reprocess`` mutation. We expose a small
 * dedicated hook to avoid the old ``useAdminData`` megahook that
 * mounted 30+ queries and 25+ ``useState`` hooks on every admin page
 * load.
 *
 * The state setters that the dialog needs (status / documentType /
 * sourcePath / mode filters) live in the operational tab's own
 * state. The shell reuses them via the shared ``AdminReprocessState``
 * context, populated by the active tab.
 */
import { createContext, useContext } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

export interface AdminReprocessFilters {
  status: string
  documentType: string
  sourcePath: string
  mode: string
}

export interface AdminReprocessState extends AdminReprocessFilters {
  setStatus: (value: string) => void
  setDocumentType: (value: string) => void
  setSourcePath: (value: string) => void
  setMode: (value: string) => void
  reprocessConfirmOpen: boolean
  setReprocessConfirmOpen: (open: boolean) => void
}

const noop = () => undefined

export const AdminReprocessContext = createContext<AdminReprocessState>({
  status: "",
  setStatus: noop,
  documentType: "",
  setDocumentType: noop,
  sourcePath: "",
  setSourcePath: noop,
  mode: "full",
  setMode: noop,
  reprocessConfirmOpen: false,
  setReprocessConfirmOpen: noop,
})

export function useAdminReprocessContext() {
  return useContext(AdminReprocessContext)
}

/**
 * Mutation hook for the bulk-reprocess action. Both the shell (for
 * the confirm dialog) and the operational tab (for the result/error
 * display) call this. The dialog reuses the filter state published
 * by the active tab through ``AdminReprocessContext``.
 */
export function useAdminReprocess() {
  const queryClient = useQueryClient()
  const filters = useAdminReprocessContext()

  const reprocess = useMutation({
    mutationFn: () =>
      api.reprocessBulk({
        status: filters.status || null,
        document_type: filters.documentType || null,
        source_path_contains: filters.sourcePath || null,
        mode: filters.mode,
        limit: 100,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["jobs"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
      void queryClient.invalidateQueries({ queryKey: ["stats"] })
    },
  })

  return {
    reprocess,
    filters,
  }
}
