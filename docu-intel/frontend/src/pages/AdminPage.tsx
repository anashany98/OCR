import { NavLink, Outlet } from "react-router-dom"

import { PageHeader } from "@/components/layout/PageHeader"
import { Button } from "@/components/ui/button"
import { ADMIN_TABS } from "@/navigation/config"

import { AdminReprocessConfirmDialog } from "./admin/useAdminOperationalData"
import { AdminReprocessContext, useAdminReprocess } from "./admin/useAdminReprocess"

/**
 * F4b - Admin shell with nested routes (refactored).
 *
 * Before: the shell called ``useAdminData()`` which mounted 30+
 * queries and 25+ ``useState`` hooks regardless of the active tab.
 * The whole admin payload hit the wire the first time the user
 * opened ``/admin`` and stayed in memory across tab switches.
 *
 * After: the shell only owns the page header, the inner tab nav
 * and the cross-cutting reprocess confirm dialog. The reprocess
 * dialog needs the active tab's filter state, so the operational
 * tab publishes those values through ``AdminReprocessContext`` and
 * the shell pulls the shared ``reprocess`` mutation from
 * ``useAdminReprocess``. Every other tab fetches its own data via
 * the per-domain ``useAdminXxxData`` hook.
 *
 * Per-tab hooks live in:
 *   * useAdminOperationalData
 *   * useAdminSystemData
 *   * useAdminIntegrationsData
 *   * useAdminAccessData
 *   * useAdminQualityData
 *   * useAdminLearningData
 */
export function AdminPage() {
  const { reprocess, filters } = useAdminReprocess()

  return (
    <AdminReprocessContext.Provider value={filters}>
      <PageHeader
        title="Administración"
        description="Operación documental, integración segura, colas y auditoría."
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {ADMIN_TABS.map(({ id: tabId, label, icon: Icon }) => (
          <Button key={tabId} asChild type="button" variant="outline" size="sm">
            <NavLink to={`/admin/${tabId}`}>
              {({ isActive }) => (
                <span
                  data-active={isActive ? "true" : undefined}
                  className="inline-flex items-center gap-1"
                >
                  <Icon data-icon="inline-start" />
                  {label}
                </span>
              )}
            </NavLink>
          </Button>
        ))}
      </div>

      <Outlet />

      <AdminReprocessConfirmDialog
        open={filters.reprocessConfirmOpen}
        title="Reprocesar documentos"
        description="Esta acción encolará nuevos jobs para los documentos que coincidan con los filtros actuales."
        confirmLabel="Reprocesar"
        confirmDisabled={reprocess.isPending}
        onCancel={() => filters.setReprocessConfirmOpen(false)}
        onConfirm={() => {
          filters.setReprocessConfirmOpen(false)
          reprocess.mutate()
        }}
      />
    </AdminReprocessContext.Provider>
  )
}
