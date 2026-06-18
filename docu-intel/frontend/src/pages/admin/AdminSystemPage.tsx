import { useEffect, useMemo, useRef, useState, type FormEvent } from "react"
import {
  Activity,
  Bell,
  CircleGauge,
  Database,
  DatabaseZap,
  HardDrive,
  Layers,
  Server,
  ShieldCheck,
  UserPlus,
} from "lucide-react"

import type {
  AdminUser,
  MaintenanceReport,
  NotificationRule,
  OperationsOverview,
  OperationsStatus,
  ProductionChecklist,
  ProductionReadiness,
  QueueStatus,
  StorageIntegrity,
  SystemHealth,
} from "@/types/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { useConfirm } from "@/hooks/useConfirm"
import { ConfigStatus, DiskLine, MetricBlock, MetricTile } from "./shared"
import { useAdminSystemData } from "./useAdminSystemData"

interface MutationLike<TData = unknown> {
  mutate: () => void
  isPending: boolean
  data?: TData
  isError: boolean
  error: Error | null
}
interface ToggleMutation {
  mutate: (args: { id: number; is_active: boolean }) => void
  isPending: boolean
}

interface SystemViewProps {
  systemHealth?: SystemHealth
  productionChecklist?: ProductionChecklist
  productionReadiness?: ProductionReadiness
  maintenanceReport?: MaintenanceReport
  storageIntegrity?: StorageIntegrity
  adminUsers: AdminUser[]
  notificationRules: NotificationRule[]
  operationsStatus?: OperationsStatus
  queueStatus?: QueueStatus
  operationsOverview?: OperationsOverview
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

type SectionDef = {
  id: string
  title: string
  description: string
  icon: React.ComponentType<{ className?: string }>
}

const SECTIONS: SectionDef[] = [
  {
    id: "postgres",
    title: "PostgreSQL",
    description: "Conexión y salud de la base de datos",
    icon: Database,
  },
  {
    id: "redis-workers",
    title: "Redis y Workers",
    description: "Colas Celery y latencia de workers",
    icon: Server,
  },
  {
    id: "storage",
    title: "Disco y almacenamiento",
    description: "Uso de disco e integridad de archivos",
    icon: HardDrive,
  },
  {
    id: "readiness",
    title: "Readiness y producción",
    description: "Checklist y readiness para puesta en producción",
    icon: ShieldCheck,
  },
  {
    id: "access",
    title: "Usuarios y notificaciones",
    description: "Cuentas admin y reglas de notificación",
    icon: UserPlus,
  },
  {
    id: "ai-config",
    title: "Configuración IA/OCR",
    description: "Motores, dimensiones y datos de demostración",
    icon: Layers,
  },
]

function SectionNav({
  sections,
  activeId,
}: {
  sections: SectionDef[]
  activeId: string
}) {
  return (
    <nav aria-label="Secciones de sistema" className="space-y-1">
      <p className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
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
                    ? "bg-primary/10 text-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground")
                }
              >
                <Icon
                  className={
                    "mt-0.5 size-4 shrink-0 transition-colors " +
                    (active ? "text-primary" : "text-muted-foreground group-hover:text-foreground")
                  }
                />
                <span className="min-w-0">
                  <span className={"block font-medium leading-tight " + (active ? "text-foreground" : "")}>
                    {s.title}
                  </span>
                  <span className="block truncate text-[11px] leading-tight text-muted-foreground">
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

function SectionHeader({
  icon: Icon,
  title,
  description,
}: {
  icon: React.ComponentType<{ className?: string }>
  title: string
  description?: string
}) {
  return (
    <div className="flex items-start gap-3 border-b pb-3">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
        <Icon className="size-4" />
      </div>
      <div className="min-w-0">
        <h3 className="text-base font-semibold leading-tight">{title}</h3>
        {description ? (
          <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>
    </div>
  )
}

function StatusBadge({ status, fallback = "sin datos" }: { status?: string; fallback?: string }) {
  const variant = status === "ok" || status === "ready" || status === "operativo"
    ? "success"
    : status
      ? "warning"
      : "neutral"
  return <Badge variant={variant}>{status ?? fallback}</Badge>
}

function readinessTone(status?: string) {
  if (status === "ready" || status === "operativo") return "success"
  if (!status) return "neutral"
  return "warning"
}

function SystemView(props: SystemViewProps) {
  const {
    systemHealth,
    productionChecklist,
    productionReadiness,
    maintenanceReport,
    storageIntegrity,
    adminUsers,
    notificationRules,
    operationsStatus,
    queueStatus,
    stats,
    adminUserEmail,
    setAdminUserEmail,
    adminUserName,
    setAdminUserName,
    adminUserRole,
    setAdminUserRole,
    adminUserPassword,
    setAdminUserPassword,
    createAdminUser,
    toggleAdminUser,
    notificationName,
    setNotificationName,
    notificationEventType,
    setNotificationEventType,
    notificationChannel,
    setNotificationChannel,
    notificationTarget,
    setNotificationTarget,
    createNotificationRule,
    seedDemo,
  } = props

  const confirm = useConfirm()

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
          // Pick the section with the largest intersection ratio; ties
          // go to the section that appears first in the document so
          // the user always moves forward when scrolling down.
          let best: { id: string; ratio: number; order: number } | null = null
          for (const [id, ratio] of visible) {
            const order = ids.indexOf(id)
            if (
              !best ||
              ratio > best.ratio ||
              (ratio === best.ratio && order < best.order)
            ) {
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

  // Top header summary tiles: derive the worst of the critical signals
  // so the operator does not have to scan every section to know if
  // something is degraded.
  const summary = useMemo(() => {
    const dbOk = systemHealth?.status === "ok"
    const readyOk = productionReadiness?.status === "ready"
    const maintenanceOk = !!maintenanceReport
    return { dbOk, readyOk, maintenanceOk }
  }, [systemHealth?.status, productionReadiness?.status, maintenanceReport])

  return (
    <div className="grid gap-8 xl:grid-cols-[220px_minmax(0,1fr)]">
      <aside className="xl:sticky xl:top-4 xl:self-start">
        <div className="rounded-lg border bg-card p-3">
          <SectionNav sections={SECTIONS} activeId={activeId} />
        </div>
      </aside>

      <div className="min-w-0 space-y-12">
        {/* Top summary strip — at-a-glance status of the critical systems */}
        <section aria-label="Resumen" className="space-y-3">
          <SectionHeader
            icon={Activity}
            title="Resumen del sistema"
            description="Indicadores críticos. Baja en cada sección para detalles."
          />
          <div className="grid gap-3 sm:grid-cols-3">
            <Card>
              <CardContent className="space-y-2 p-5">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Database className="size-4 text-muted-foreground" />
                  PostgreSQL
                </div>
                <StatusBadge status={summary.dbOk ? "ok" : "degradado"} />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="space-y-2 p-5">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <ShieldCheck className="size-4 text-muted-foreground" />
                  Readiness
                </div>
                <StatusBadge status={summary.readyOk ? "ready" : "degradado"} />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="space-y-2 p-5">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <CircleGauge className="size-4 text-muted-foreground" />
                  Mantenimiento
                </div>
                <StatusBadge status={summary.maintenanceOk ? "ok" : "sin datos"} />
              </CardContent>
            </Card>
          </div>
        </section>

        <section
          id="postgres"
          ref={setSectionRef("postgres")}
          aria-labelledby="postgres-title"
          className="scroll-mt-6 space-y-4"
        >
          <h4 id="postgres-title" className="sr-only">PostgreSQL</h4>
          <SectionHeader
            icon={Database}
            title="PostgreSQL"
            description="Conexión y salud de la base de datos"
          />
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardContent className="space-y-3 p-6">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Checks en vivo
                </p>
                <div className="flex flex-wrap gap-2">
                  <Badge variant={systemHealth?.status === "ok" ? "success" : "warning"}>
                    {systemHealth?.status ?? "sin datos"}
                  </Badge>
                  {Object.entries(systemHealth?.checks ?? {})
                    .filter(([k]) => k === "database" || k === "postgresql")
                    .map(([key, check]) => (
                      <Badge key={key} variant={check.status === "ok" ? "outline" : "warning"}>
                        {key}: {check.status}
                      </Badge>
                    ))}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="space-y-3 p-6">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Estado operativo
                </p>
                <ConfigStatus
                  label="Estado"
                  value={systemHealth?.status === "ok" ? "operativo" : "degradado"}
                  tone={systemHealth?.status === "ok" ? "success" : "warning"}
                />
              </CardContent>
            </Card>
          </div>
        </section>

        <section
          id="redis-workers"
          ref={setSectionRef("redis-workers")}
          aria-labelledby="redis-workers-title"
          className="scroll-mt-6 space-y-4"
        >
          <h4 id="redis-workers-title" className="sr-only">Redis y Workers</h4>
          <SectionHeader
            icon={Server}
            title="Redis y Workers"
            description="Colas Celery y latencia de workers"
          />
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardContent className="space-y-3 p-6">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Estado de workers
                </p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(systemHealth?.checks ?? {})
                    .filter(([k]) => k === "redis" || k === "celery" || k === "worker")
                    .map(([key, check]) => (
                      <Badge
                        key={key}
                        variant={
                          check.status === "ok"
                            ? "success"
                            : check.status === "warning"
                              ? "warning"
                              : "danger"
                        }
                      >
                        {key}: {check.status}
                      </Badge>
                    ))}
                  {Object.keys(systemHealth?.checks ?? {}).filter(
                    (k) => k === "redis" || k === "celery" || k === "worker",
                  ).length === 0 && (
                    <p className="text-sm text-muted-foreground">Sin datos de workers.</p>
                  )}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="space-y-3 p-6">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Colas por tipo
                </p>
                <MetricBlock
                  title=""
                  values={
                    queueStatus?.queues
                      ? Object.fromEntries(
                          Object.entries(queueStatus.queues).map(([k, v]) => [k, v.pending ?? 0]),
                        )
                      : undefined
                  }
                />
              </CardContent>
            </Card>
          </div>
        </section>

        <section
          id="storage"
          ref={setSectionRef("storage")}
          aria-labelledby="storage-title"
          className="scroll-mt-6 space-y-4"
        >
          <h4 id="storage-title" className="sr-only">Disco y almacenamiento</h4>
          <SectionHeader
            icon={HardDrive}
            title="Disco y almacenamiento"
            description="Uso de disco e integridad de archivos"
          />
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardContent className="space-y-4 p-6">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Volúmenes montados
                </p>
                <DiskLine label="Directorio de entrada" usage={operationsStatus?.disk?.input_dir} />
                <DiskLine label="Archivos originales" usage={operationsStatus?.disk?.files_dir} />
              </CardContent>
            </Card>
            <Card>
              <CardContent className="space-y-4 p-6">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Integridad de almacenamiento
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <MetricTile
                    label="Comprobados"
                    value={String(storageIntegrity?.checked_documents ?? 0)}
                  />
                  <MetricTile
                    label="Sin fichero"
                    value={String(storageIntegrity?.missing_files ?? 0)}
                  />
                  <MetricTile
                    label="Huérfanos"
                    value={String(storageIntegrity?.orphan_files ?? 0)}
                  />
                  <MetricTile
                    label="Hash dudoso"
                    value={String(storageIntegrity?.hash_mismatches ?? 0)}
                  />
                </div>
              </CardContent>
            </Card>
          </div>
        </section>

        <section
          id="readiness"
          ref={setSectionRef("readiness")}
          aria-labelledby="readiness-title"
          className="scroll-mt-6 space-y-4"
        >
          <h4 id="readiness-title" className="sr-only">Readiness y producción</h4>
          <SectionHeader
            icon={ShieldCheck}
            title="Readiness y producción"
            description="Checklist y readiness para puesta en producción"
          />
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardContent className="space-y-4 p-6">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">Readiness productivo</p>
                  <Badge
                    variant={productionReadiness?.status === "ready" ? "success" : "warning"}
                  >
                    {productionReadiness?.status ?? "sin datos"}
                  </Badge>
                </div>
                <div className="grid gap-2 text-sm sm:grid-cols-2">
                  {(productionReadiness?.checks ?? []).map((check) => (
                    <div key={check.key} className="rounded-md border bg-background p-3">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium">{check.key}</p>
                        <Badge
                          variant={
                            check.status === "ok"
                              ? "success"
                              : check.status === "error"
                                ? "destructive"
                                : "warning"
                          }
                        >
                          {check.status}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                        {check.description}
                      </p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="space-y-4 p-6">
                <p className="text-sm font-medium">Checklist de producción</p>
                <div className="grid gap-2 text-sm sm:grid-cols-2">
                  {(productionChecklist?.items ?? []).map((item) => (
                    <div key={item.key} className="rounded-md border bg-background p-3">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium">{item.title}</p>
                        <Badge
                          variant={
                            item.status === "ok"
                              ? "success"
                              : item.status === "error"
                                ? "destructive"
                                : "warning"
                          }
                        >
                          {item.status}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                        {item.description}
                      </p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </section>

        <section
          id="access"
          ref={setSectionRef("access")}
          aria-labelledby="access-title"
          className="scroll-mt-6 space-y-4"
        >
          <h4 id="access-title" className="sr-only">Usuarios y notificaciones</h4>
          <SectionHeader
            icon={UserPlus}
            title="Usuarios y notificaciones"
            description="Cuentas admin y reglas de notificación"
          />
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardContent className="space-y-4 p-6">
                <div className="flex items-center gap-2">
                  <UserPlus className="size-4 text-muted-foreground" />
                  <p className="text-sm font-medium">Crear usuario admin</p>
                </div>
                <form
                  className="grid gap-2 md:grid-cols-2"
                  onSubmit={(e: FormEvent) => {
                    e.preventDefault()
                    if (
                      adminUserEmail.trim() &&
                      adminUserName.trim() &&
                      adminUserPassword.length >= 12
                    )
                      createAdminUser.mutate()
                  }}
                >
                  <Input
                    value={adminUserEmail}
                    onChange={(e) => setAdminUserEmail(e.target.value)}
                    placeholder="email@empresa.com"
                    className="h-9"
                  />
                  <Input
                    value={adminUserName}
                    onChange={(e) => setAdminUserName(e.target.value)}
                    placeholder="Nombre"
                    className="h-9"
                  />
                  <select
                    className="h-9 rounded-md border bg-background px-2 text-sm"
                    value={adminUserRole}
                    onChange={(e) => setAdminUserRole(e.target.value)}
                  >
                    <option value="operario">Operario</option>
                    <option value="gestor">Gestor</option>
                    <option value="auditor">Auditor</option>
                    <option value="admin">Admin</option>
                  </select>
                  <Input
                    type="password"
                    value={adminUserPassword}
                    onChange={(e) => setAdminUserPassword(e.target.value)}
                    placeholder="Contraseña (12+ caracteres)"
                    className="h-9"
                  />
                  <div className="md:col-span-2 flex items-center justify-between gap-2">
                    <p className="text-[11px] text-muted-foreground">
                      Mínimo 12 caracteres. El usuario recibirá acceso inmediato al rol seleccionado.
                    </p>
                    <Button
                      disabled={createAdminUser.isPending || adminUserPassword.length < 12}
                    >
                      Crear usuario
                    </Button>
                  </div>
                </form>
                {createAdminUser.isError && (
                  <p className="text-sm text-destructive">{createAdminUser.error?.message}</p>
                )}
                <div className="max-h-[240px] overflow-auto rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-xs">Usuario</TableHead>
                        <TableHead className="text-xs">Rol</TableHead>
                        <TableHead className="text-xs">Estado</TableHead>
                        <TableHead className="text-xs" />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {adminUsers.map((u) => (
                        <TableRow key={u.id}>
                          <TableCell>
                            <p className="text-xs font-medium">{u.name}</p>
                            <p className="text-[10px] text-muted-foreground">{u.email}</p>
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-[10px]">
                              {u.role}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant={u.is_active ? "success" : "neutral"}
                              className="text-[10px]"
                            >
                              {u.is_active ? "activo" : "inactivo"}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              className="h-7 text-xs"
                              onClick={() =>
                                toggleAdminUser.mutate({ id: u.id, is_active: !u.is_active })
                              }
                            >
                              {u.is_active ? "Desactivar" : "Activar"}
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="space-y-4 p-6">
                <div className="flex items-center gap-2">
                  <Bell className="size-4 text-muted-foreground" />
                  <p className="text-sm font-medium">Crear regla de notificación</p>
                </div>
                <form
                  className="grid gap-2 md:grid-cols-2"
                  onSubmit={(e: FormEvent) => {
                    e.preventDefault()
                    if (notificationName.trim() && notificationTarget.trim())
                      createNotificationRule.mutate()
                  }}
                >
                  <Input
                    value={notificationName}
                    onChange={(e) => setNotificationName(e.target.value)}
                    placeholder="Nombre regla"
                    className="h-9"
                  />
                  <Input
                    value={notificationEventType}
                    onChange={(e) => setNotificationEventType(e.target.value)}
                    placeholder="Evento"
                    className="h-9"
                  />
                  <select
                    className="h-9 rounded-md border bg-background px-2 text-sm"
                    value={notificationChannel}
                    onChange={(e) => setNotificationChannel(e.target.value)}
                  >
                    <option value="webhook">Webhook</option>
                    <option value="email">Email</option>
                    <option value="teams">Teams</option>
                  </select>
                  <Input
                    value={notificationTarget}
                    onChange={(e) => setNotificationTarget(e.target.value)}
                    placeholder="URL o email"
                    className="h-9"
                  />
                  <div className="md:col-span-2 flex justify-end">
                    <Button disabled={createNotificationRule.isPending}>Crear regla</Button>
                  </div>
                </form>
                {createNotificationRule.isError && (
                  <p className="text-sm text-destructive">
                    {createNotificationRule.error?.message}
                  </p>
                )}
                <div className="space-y-2">
                  {notificationRules.map((rule) => (
                    <div key={rule.id} className="rounded-md border bg-background p-3 text-sm">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium">{rule.name}</p>
                        <Badge
                          variant={rule.is_active ? "success" : "neutral"}
                          className="text-[10px]"
                        >
                          {rule.channel}
                        </Badge>
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {rule.event_type} → {rule.target}
                      </p>
                    </div>
                  ))}
                  {!notificationRules.length && (
                    <p className="text-sm text-muted-foreground">Sin reglas.</p>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </section>

        <section
          id="ai-config"
          ref={setSectionRef("ai-config")}
          aria-labelledby="ai-config-title"
          className="scroll-mt-6 space-y-4"
        >
          <h4 id="ai-config-title" className="sr-only">Configuración IA/OCR</h4>
          <SectionHeader
            icon={Layers}
            title="Configuración IA/OCR"
            description="Motores, dimensiones y datos de demostración"
          />
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardContent className="space-y-4 p-6">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Estado de configuración
                </p>
                <div className="grid gap-3 sm:grid-cols-2">
                  <ConfigStatus
                    label="Readiness"
                    value={productionReadiness?.status ?? "-"}
                    tone={readinessTone(productionReadiness?.status)}
                  />
                  <ConfigStatus label="OCR" value="paddleocr" tone="neutral" />
                  <ConfigStatus label="Embeddings" value="backend" tone="neutral" />
                  <ConfigStatus
                    label="Backups"
                    value={maintenanceReport ? "auditable" : "sin datos"}
                    tone={maintenanceReport ? "success" : "warning"}
                  />
                </div>
                <div className="rounded-md border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
                  <div>AI_PROVIDER=local_openai_compatible</div>
                  <div>OCR_ENGINE=paddleocr</div>
                  <div>Docs en revisión: {stats?.documents_needs_review ?? "-"}</div>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="space-y-4 p-6">
                <div className="flex items-center gap-2">
                  <DatabaseZap className="size-4 text-muted-foreground" />
                  <p className="text-sm font-medium">Datos de demostración</p>
                </div>
                <p className="text-sm text-muted-foreground">
                  Crea un conjunto reducido de documentos, presupuestos y pedidos para mostrar el
                  funcionamiento del sistema sin afectar datos reales.
                </p>
                <div className="flex items-center gap-3">
                  <Button
                    type="button"
                    onClick={async () => {
                      const ok = await confirm({
                        title: "¿Activar datos demo?",
                        description:
                          "Se crearán documentos y datos de ejemplo. La operación queda registrada en la auditoría.",
                        confirmLabel: "Activar demo",
                        tone: "default",
                      })
                      if (ok) seedDemo.mutate()
                    }}
                    disabled={seedDemo.isPending}
                  >
                    <DatabaseZap data-icon="inline-start" />
                    Activar demo
                  </Button>
                  {seedDemo.data && <Badge variant="success">Demo preparado</Badge>}
                  {seedDemo.isError && (
                    <span className="text-sm text-destructive">{seedDemo.error?.message}</span>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </section>
      </div>
    </div>
  )
}

/** F4b - System admin sub-page. Lazy-loaded via the router. */
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
