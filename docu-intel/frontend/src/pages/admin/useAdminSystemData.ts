/**
 * useAdminSystemData - queries and state for the
 * ``/admin/sistema`` tab (system health, readiness, admin users,
 * notification rules, demo seed).
 */
import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

export function useAdminSystemData() {
  const queryClient = useQueryClient()

  const [adminUserEmail, setAdminUserEmail] = useState("")
  const [adminUserName, setAdminUserName] = useState("")
  const [adminUserRole, setAdminUserRole] = useState("operario")
  const [adminUserPassword, setAdminUserPassword] = useState("")
  const [notificationName, setNotificationName] = useState("")
  const [notificationEventType, setNotificationEventType] = useState("ocr_failed")
  const [notificationChannel, setNotificationChannel] = useState("webhook")
  const [notificationTarget, setNotificationTarget] = useState("")

  const systemHealth = useQuery({
    queryKey: ["system-health"],
    queryFn: api.systemHealth,
    refetchInterval: 15000,
  })
  const productionChecklist = useQuery({
    queryKey: ["production-checklist"],
    queryFn: api.productionChecklist,
    refetchInterval: 30000,
  })
  const productionReadiness = useQuery({
    queryKey: ["production-readiness"],
    queryFn: api.productionReadiness,
    refetchInterval: 30000,
  })
  const storageIntegrity = useQuery({
    queryKey: ["storage-integrity"],
    queryFn: () => api.storageIntegrity(1000),
    refetchInterval: 30000,
  })
  const maintenanceReport = useQuery({
    queryKey: ["maintenance-report"],
    queryFn: api.maintenanceReport,
    refetchInterval: 15000,
  })
  const adminUsers = useQuery({ queryKey: ["admin-users"], queryFn: api.adminUsers })
  const notificationRules = useQuery({
    queryKey: ["notification-rules"],
    queryFn: api.notificationRules,
  })
  // These are used by the system tab's overview widgets but live in
  // other tabs' domains; the same TanStack ``queryKey`` dedupes the
  // fetch so the operational tab's mount fills the cache.
  const queueStatus = useQuery({ queryKey: ["queues"], queryFn: api.queues, refetchInterval: 5000 })
  const operationsStatus = useQuery({
    queryKey: ["operations-status"],
    queryFn: api.operationsStatus,
    refetchInterval: 5000,
  })
  const operationsOverview = useQuery({
    queryKey: ["operations-overview"],
    queryFn: api.operationsOverview,
    refetchInterval: 5000,
  })
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats })

  const createAdminUser = useMutation({
    mutationFn: () =>
      api.createAdminUser({
        email: adminUserEmail.trim(),
        name: adminUserName.trim(),
        role: adminUserRole,
        password: adminUserPassword,
      }),
    onSuccess: () => {
      setAdminUserEmail("")
      setAdminUserName("")
      setAdminUserPassword("")
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const toggleAdminUser = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      api.updateAdminUser(id, { is_active }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const createNotificationRule = useMutation({
    mutationFn: () =>
      api.createNotificationRule({
        name: notificationName.trim(),
        event_type: notificationEventType,
        channel: notificationChannel,
        target: notificationTarget.trim(),
      }),
    onSuccess: () => {
      setNotificationName("")
      setNotificationTarget("")
      void queryClient.invalidateQueries({ queryKey: ["notification-rules"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const seedDemo = useMutation({
    mutationFn: () => api.seedDemo(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["system-health"] })
      void queryClient.invalidateQueries({ queryKey: ["queues"] })
      void queryClient.invalidateQueries({ queryKey: ["stats"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })

  return {
    state: {
      adminUserEmail,
      setAdminUserEmail,
      adminUserName,
      setAdminUserName,
      adminUserRole,
      setAdminUserRole,
      adminUserPassword,
      setAdminUserPassword,
      notificationName,
      setNotificationName,
      notificationEventType,
      setNotificationEventType,
      notificationChannel,
      setNotificationChannel,
      notificationTarget,
      setNotificationTarget,
    },
    queries: {
      systemHealth,
      productionChecklist,
      productionReadiness,
      storageIntegrity,
      maintenanceReport,
      adminUsers,
      notificationRules,
      queueStatus,
      operationsStatus,
      operationsOverview,
      stats,
    },
    mutations: { createAdminUser, toggleAdminUser, createNotificationRule, seedDemo },
  }
}

export type AdminSystemData = ReturnType<typeof useAdminSystemData>
