import { AdminSystemTab } from "./AdminSystemTab"
import { useAdminSystemData } from "./useAdminSystemData"

/**
 * F4b - System admin sub-route. Lazy-loaded via the router.
 *
 * Mounts ``useAdminSystemData`` so the system tab fetches only
 * its own queries. Some queries (``queueStatus``,
 * ``operationsStatus``) are shared with the operational tab via
 * the same ``queryKey`` — TanStack Query dedupes the network call
 * so mounting both tabs is cheap.
 */
export function AdminSystemRoute() {
  const { state, queries, mutations } = useAdminSystemData()

  return (
    <AdminSystemTab
      systemHealth={queries.systemHealth.data}
      productionChecklist={queries.productionChecklist.data}
      productionReadiness={queries.productionReadiness.data}
      maintenanceReport={queries.maintenanceReport.data}
      storageIntegrity={queries.storageIntegrity.data}
      adminUsers={queries.adminUsers.data ?? []}
      notificationRules={queries.notificationRules.data ?? []}
      operationsStatus={queries.operationsStatus.data}
      queueStatus={queries.queueStatus.data}
      operationsOverview={queries.operationsOverview.data}
      stats={queries.stats.data}
      adminUserEmail={state.adminUserEmail}
      setAdminUserEmail={state.setAdminUserEmail}
      adminUserName={state.adminUserName}
      setAdminUserName={state.setAdminUserName}
      adminUserRole={state.adminUserRole}
      setAdminUserRole={state.setAdminUserRole}
      adminUserPassword={state.adminUserPassword}
      setAdminUserPassword={state.setAdminUserPassword}
      createAdminUser={{
        mutate: () => mutations.createAdminUser.mutate(),
        isPending: mutations.createAdminUser.isPending,
        data: mutations.createAdminUser.data,
        isError: mutations.createAdminUser.isError,
        error: mutations.createAdminUser.error,
      }}
      toggleAdminUser={{
        mutate: mutations.toggleAdminUser.mutate,
        isPending: mutations.toggleAdminUser.isPending,
      }}
      notificationName={state.notificationName}
      setNotificationName={state.setNotificationName}
      notificationEventType={state.notificationEventType}
      setNotificationEventType={state.setNotificationEventType}
      notificationChannel={state.notificationChannel}
      setNotificationChannel={state.setNotificationChannel}
      notificationTarget={state.notificationTarget}
      setNotificationTarget={state.setNotificationTarget}
      createNotificationRule={{
        mutate: () => mutations.createNotificationRule.mutate(),
        isPending: mutations.createNotificationRule.isPending,
        data: mutations.createNotificationRule.data,
        isError: mutations.createNotificationRule.isError,
        error: mutations.createNotificationRule.error,
      }}
      seedDemo={{
        mutate: () => mutations.seedDemo.mutate(),
        isPending: mutations.seedDemo.isPending,
        data: mutations.seedDemo.data,
        isError: mutations.seedDemo.isError,
        error: mutations.seedDemo.error,
      }}
    />
  )
}
