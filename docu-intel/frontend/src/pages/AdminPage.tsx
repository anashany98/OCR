import { NavLink, Outlet } from "react-router-dom"

import { PageHeader } from "@/components/layout/PageHeader"
import { Button } from "@/components/ui/button"
import { ADMIN_TABS } from "@/routes/adminTabs"

import { AdminReprocessConfirmDialog, useAdminData } from "./admin/useAdminData"

/**
 * F4b - Admin shell with nested routes.
 *
 * The previous 33 KB ``AdminPage`` mounted 30+ queries and 25+
 * ``useState`` hooks regardless of the active tab. F4b splits that
 * out: this component only renders the page header, the inner tab
 * navigation and an ``<Outlet />``. Each child route
 * (``/admin/operativa``, ``/admin/sistema`` …) is ``React.lazy`` and
 * calls :func:`useAdminData` on demand; TanStack Query dedupes the
 * network calls so the second tab to mount reuses the cache.
 *
 * Note: the reprocess confirm dialog is still owned by the shell
 * because it is a cross-cutting piece of UI that is rendered
 * regardless of which tab is active. It hooks into the data layer
 * because it has to call the same ``reprocess`` mutation as the
 * operational tab.
 */
export function AdminPage() {
  const data = useAdminData()

  return (
    <>
      <PageHeader
        title="Administración"
        description="Operación documental, integración segura, colas y auditoría."
      />
      <div className="mb-4 flex flex-wrap gap-2">
        {ADMIN_TABS.map(({ id: tabId, label, icon: Icon }) => (
          <Button
            key={tabId}
            asChild
            type="button"
            variant="outline"
            size="sm"
          >
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
        open={data.state.reprocessConfirmOpen}
        title="Reprocesar documentos"
        description="Esta acción encolará nuevos jobs para los documentos que coincidan con los filtros actuales."
        confirmLabel="Reprocesar"
        confirmDisabled={data.mutations.reprocess.isPending}
        onCancel={() => data.state.setReprocessConfirmOpen(false)}
        onConfirm={data.handlers.confirmReprocess}
      />
    </>
  )
}
