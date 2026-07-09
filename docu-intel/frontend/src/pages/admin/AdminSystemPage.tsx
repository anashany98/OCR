import { useState } from "react"
import { Database, HardDrive, Layers, Server, ShieldCheck, UserPlus } from "lucide-react"

import { AutoBreadcrumbs } from "@/components/layout/AutoBreadcrumbs"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  AccessSection,
  AiConfigSection,
  PostgresSection,
  ReadinessSection,
  RedisWorkersSection,
  StorageSection,
  SystemSummarySection,
} from "./system-sections"
import { useAdminSystemData } from "./useAdminSystemData"

const TABS = [
  { id: "resumen", label: "Resumen", icon: Database },
  { id: "infra", label: "Infraestructura", icon: Server },
  { id: "usuarios", label: "Usuarios", icon: UserPlus },
  { id: "ia", label: "IA/OCR", icon: Layers },
]

export function AdminSystemPage() {
  const { queries } = useAdminSystemData()
  const [tab, setTab] = useState("resumen")

  return (
    <div className="space-y-4">
      <AutoBreadcrumbs />

      <div>
        <h1 className="text-[18px] font-semibold text-[var(--text-primary)]">Estado del sistema</h1>
        <p className="text-[12px] text-[var(--text-muted)]">Monitoreo de infraestructura, usuarios y configuración.</p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="w-full justify-start rounded-lg bg-[var(--bg-surface-2)] p-0.5">
          {TABS.map((t) => {
            const Icon = t.icon
            return (
              <TabsTrigger key={t.id} value={t.id} className="gap-1.5 text-[12px] px-4">
                <Icon className="h-3.5 w-3.5" /> {t.label}
              </TabsTrigger>
            )
          })}
        </TabsList>

        <TabsContent value="resumen" className="mt-4 space-y-4">
          <SystemSummarySection
            systemHealth={queries.systemHealth.data}
            productionReadiness={queries.productionReadiness.data}
            maintenanceReport={queries.maintenanceReport.data}
          />
          <PostgresSection systemHealth={queries.systemHealth.data} />
          <RedisWorkersSection systemHealth={queries.systemHealth.data} queueStatus={queries.queueStatus.data} />
          <StorageSection operationsStatus={queries.operationsStatus.data} storageIntegrity={queries.storageIntegrity.data} />
          <ReadinessSection productionReadiness={queries.productionReadiness.data} productionChecklist={queries.productionChecklist.data} />
        </TabsContent>

        <TabsContent value="infra" className="mt-4 space-y-4">
          <PostgresSection systemHealth={queries.systemHealth.data} />
          <RedisWorkersSection systemHealth={queries.systemHealth.data} queueStatus={queries.queueStatus.data} />
          <StorageSection operationsStatus={queries.operationsStatus.data} storageIntegrity={queries.storageIntegrity.data} />
          <ReadinessSection productionReadiness={queries.productionReadiness.data} productionChecklist={queries.productionChecklist.data} />
        </TabsContent>

        <TabsContent value="usuarios" className="mt-4">
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-6 text-center text-[13px] text-[var(--text-muted)]">
            <UserPlus className="mx-auto mb-2 h-8 w-8 text-[var(--text-muted)]" />
            <p>Gestión de usuarios en <a href="/admin/acceso" className="text-[var(--accent)] hover:underline">Admin → Acceso</a></p>
          </div>
        </TabsContent>

        <TabsContent value="ia" className="mt-4">
          <AiConfigSection
            productionReadiness={queries.productionReadiness.data}
            maintenanceReport={queries.maintenanceReport.data}
            stats={queries.stats.data}
            seedDemo={{ mutate: () => {}, isPending: false, data: undefined, isError: false, error: null }}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}
