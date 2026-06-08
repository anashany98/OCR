import { useOutletContext } from "react-router-dom"

import { AdminSystemTab } from "./AdminSystemTab"
import type { AdminData } from "./useAdminData"

export function AdminSystemRoute() {
  const data = useOutletContext<AdminData>()
  const { state, queries, mutations } = data

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
      toggleAdminUser={{ mutate: mutations.toggleAdminUser.mutate, isPending: mutations.toggleAdminUser.isPending }}
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
