import type {
  AdminUser,
  MaintenanceReport,
  NotificationRule,
  OperationsStatus,
  ProductionChecklist,
  ProductionReadiness,
  QueueStatus,
  StorageIntegrity,
  SystemHealth,
} from "@/types/api"

export interface MutationLike<TData = unknown> {
  mutate: () => void
  isPending: boolean
  data?: TData
  isError: boolean
  error: Error | null
}

export interface ToggleMutation {
  mutate: (args: { id: number; is_active: boolean }) => void
  isPending: boolean
}

export interface SystemViewProps {
  systemHealth?: SystemHealth
  productionChecklist?: ProductionChecklist
  productionReadiness?: ProductionReadiness
  maintenanceReport?: MaintenanceReport
  storageIntegrity?: StorageIntegrity
  adminUsers: AdminUser[]
  notificationRules: NotificationRule[]
  operationsStatus?: OperationsStatus
  queueStatus?: QueueStatus
  stats?: { documents_needs_review?: number }
  adminUserEmail: string
  setAdminUserEmail: (v: string) => void
  adminUserName: string
  setAdminUserName: (v: string) => void
  adminUserRole: string
  setAdminUserRole: (v: string) => void
  adminUserPassword: string
  setAdminUserPassword: (v: string) => void
  createAdminUser: MutationLike
  toggleAdminUser: ToggleMutation
  notificationName: string
  setNotificationName: (v: string) => void
  notificationEventType: string
  setNotificationEventType: (v: string) => void
  notificationChannel: string
  setNotificationChannel: (v: string) => void
  notificationTarget: string
  setNotificationTarget: (v: string) => void
  createNotificationRule: MutationLike
  seedDemo: MutationLike<{ seeded: boolean }>
}

export type SectionDef = {
  id: string
  title: string
  description: string
  icon: React.ComponentType<{ className?: string }>
}
