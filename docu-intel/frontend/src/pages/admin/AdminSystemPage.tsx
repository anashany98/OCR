import { useEffect, useMemo, useRef, useState } from "react"
import { Database, HardDrive, Layers, Server, ShieldCheck, UserPlus } from "lucide-react"

import {
  AccessSection,
  AiConfigSection,
  PostgresSection,
  ReadinessSection,
  RedisWorkersSection,
  StatusBadge,
  StorageSection,
  SystemSummarySection,
} from "./system-sections"
import type { SectionDef, SystemViewProps } from "./system-types"
import { useAdminSystemData } from "./useAdminSystemData"

const SECTIONS: SectionDef[] = [
  { id: "postgres", title: "PostgreSQL", description: "Conexión y salud de la base de datos", icon: Database },
  { id: "redis-workers", title: "Redis y Workers", description: "Colas Celery y latencia de workers", icon: Server },
  { id: "storage", title: "Disco y almacenamiento", description: "Uso de disco e integridad de archivos", icon: HardDrive },
  { id: "readiness", title: "Readiness y producción", description: "Checklist y readiness para producción", icon: ShieldCheck },
  { id: "access", title: "Usuarios y notificaciones", description: "Cuentas admin y reglas de notificación", icon: UserPlus },
  { id: "ai-config", title: "Configuración IA/OCR", description: "Motores, dimensiones y datos demo", icon: Layers },
]

function SectionNav({ sections, activeId }: { sections: SectionDef[]; activeId: string }) {
  return (
    <nav aria-label="Secciones de sistema" className="space-y-1">
      <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
        Secciones
      </p>
      <ul className="space-y-0.5">
        {sections.map((s) => {
          const Icon = s.icon
          const active = activeId === s.id
          return (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                aria-current={active ? "true" : undefined}
                className={
                  "group flex items-start gap-2.5 rounded-md px-3 py-2 text-sm transition-colors " +
                  (active
                    ? "bg-[var(--accent-light)] text-[var(--text-primary)]"
                    : "text-[var(--text-muted)] hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-primary)]")
                }
              >
                <Icon
                  className={
                    "mt-0.5 size-4 shrink-0 transition-colors " +
                    (active ? "text-[var(--accent)]" : "text-[var(--text-muted)] group-hover:text-[var(--text-primary)]")
                  }
                />
                <span className="min-w-0">
                  <span className={"block font-medium leading-tight " + (active ? "text-[var(--text-primary)]" : "")}>
                    {s.title}
                  </span>
                  <span className="block truncate text-[11px] leading-tight text-[var(--text-muted)]">
                    {s.description}
                  </span>
                </span>
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

function SystemView(props: SystemViewProps) {
  const sectionRefs = useRef<Record<string, HTMLElement | null>>({})
  const [activeId, setActiveId] = useState<string>(SECTIONS[0].id)

  useEffect(() => {
    const ids = SECTIONS.map((s) => s.id)
    const visible = new Map<string, number>()

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = (entry.target as HTMLElement).id
          if (entry.isIntersecting) {
            visible.set(id, entry.intersectionRatio)
          } else {
            visible.delete(id)
          }
        }
        if (visible.size > 0) {
          let best: { id: string; ratio: number; order: number } | null = null
          for (const [id, ratio] of visible) {
            const order = ids.indexOf(id)
            if (!best || ratio > best.ratio || (ratio === best.ratio && order < best.order)) {
              best = { id, ratio, order }
            }
          }
          if (best) setActiveId(best.id)
        }
      },
      { rootMargin: "-30% 0px -50% 0px", threshold: [0, 0.25, 0.5, 0.75, 1] },
    )

    for (const id of ids) {
      const el = sectionRefs.current[id]
      if (el) observer.observe(el)
    }
    return () => observer.disconnect()
  }, [])

  const setSectionRef = (id: string) => (el: HTMLElement | null) => {
    sectionRefs.current[id] = el
  }

  return (
    <div className="grid gap-8 xl:grid-cols-[220px_minmax(0,1fr)]">
      <aside className="xl:sticky xl:top-4 xl:self-start">
        <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-3">
          <SectionNav sections={SECTIONS} activeId={activeId} />
        </div>
      </aside>

      <div className="min-w-0 space-y-12">
        <SystemSummarySection
          systemHealth={props.systemHealth}
          productionReadiness={props.productionReadiness}
          maintenanceReport={props.maintenanceReport}
        />
        <div ref={setSectionRef("postgres")}>
          <PostgresSection systemHealth={props.systemHealth} />
        </div>
        <div ref={setSectionRef("redis-workers")}>
          <RedisWorkersSection systemHealth={props.systemHealth} queueStatus={props.queueStatus} />
        </div>
        <div ref={setSectionRef("storage")}>
          <StorageSection operationsStatus={props.operationsStatus} storageIntegrity={props.storageIntegrity} />
        </div>
        <div ref={setSectionRef("readiness")}>
          <ReadinessSection productionReadiness={props.productionReadiness} productionChecklist={props.productionChecklist} />
        </div>
        <div ref={setSectionRef("access")}>
          <AccessSection {...props} />
        </div>
        <div ref={setSectionRef("ai-config")}>
          <AiConfigSection
            productionReadiness={props.productionReadiness}
            maintenanceReport={props.maintenanceReport}
            stats={props.stats}
            seedDemo={props.seedDemo}
          />
        </div>
      </div>
    </div>
  )
}

export function AdminSystemPage() {
  const { state, queries, mutations } = useAdminSystemData()

  return (
    <SystemView
      systemHealth={queries.systemHealth.data}
      productionChecklist={queries.productionChecklist.data}
      productionReadiness={queries.productionReadiness.data}
      maintenanceReport={queries.maintenanceReport.data}
      storageIntegrity={queries.storageIntegrity.data}
      adminUsers={queries.adminUsers.data ?? []}
      notificationRules={queries.notificationRules.data ?? []}
      operationsStatus={queries.operationsStatus.data}
      queueStatus={queries.queueStatus.data}
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
