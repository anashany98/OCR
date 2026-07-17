import { type FormEvent } from "react"
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

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { StyledSelect } from "@/components/ui/styled-select"
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
import type { SystemViewProps } from "./system-types"

export {
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
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

export function StatusBadge({
  status,
  fallback = "sin datos",
}: {
  status?: string
  fallback?: string
}) {
  const variant =
    status === "ok" || status === "ready" || status === "operativo"
      ? "success"
      : status
        ? "warning"
        : "neutral"
  return <Badge variant={variant}>{status ?? fallback}</Badge>
}

export function readinessTone(status?: string) {
  if (status === "ready" || status === "operativo") return "success"
  if (!status) return "neutral"
  return "warning"
}

export function SectionHeader({
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
      <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-[var(--accent-light)] text-[var(--accent)]">
        <Icon className="size-4" />
      </div>
      <div className="min-w-0">
        <h3 className="text-base font-semibold leading-tight">{title}</h3>
        {description ? (
          <p className="mt-0.5 text-xs text-[var(--text-muted)]">{description}</p>
        ) : null}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Summary section
// ---------------------------------------------------------------------------

export function SystemSummarySection({
  systemHealth,
  productionReadiness,
  maintenanceReport,
}: Pick<SystemViewProps, "systemHealth" | "productionReadiness" | "maintenanceReport">) {
  const dbOk = systemHealth?.status === "ok"
  const readyOk = productionReadiness?.status === "ready"
  const maintenanceOk = !!maintenanceReport

  return (
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
              <Database className="size-4 text-[var(--text-muted)]" />
              PostgreSQL
            </div>
            <StatusBadge status={dbOk ? "ok" : "degradado"} />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-2 p-5">
            <div className="flex items-center gap-2 text-sm font-medium">
              <ShieldCheck className="size-4 text-[var(--text-muted)]" />
              Readiness
            </div>
            <StatusBadge status={readyOk ? "ready" : "degradado"} />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-2 p-5">
            <div className="flex items-center gap-2 text-sm font-medium">
              <CircleGauge className="size-4 text-[var(--text-muted)]" />
              Mantenimiento
            </div>
            <StatusBadge status={maintenanceOk ? "ok" : "sin datos"} />
          </CardContent>
        </Card>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// PostgreSQL section
// ---------------------------------------------------------------------------

export function PostgresSection({ systemHealth }: Pick<SystemViewProps, "systemHealth">) {
  return (
    <section id="postgres" aria-labelledby="postgres-title" className="scroll-mt-6 space-y-4">
      <h4 id="postgres-title" className="sr-only">
        PostgreSQL
      </h4>
      <SectionHeader
        icon={Database}
        title="PostgreSQL"
        description="Conexión y salud de la base de datos"
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="space-y-3 p-6">
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
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
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
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
  )
}

// ---------------------------------------------------------------------------
// Redis & Workers section
// ---------------------------------------------------------------------------

export function RedisWorkersSection({
  systemHealth,
  queueStatus,
}: Pick<SystemViewProps, "systemHealth" | "queueStatus">) {
  return (
    <section
      id="redis-workers"
      aria-labelledby="redis-workers-title"
      className="scroll-mt-6 space-y-4"
    >
      <h4 id="redis-workers-title" className="sr-only">
        Redis y Workers
      </h4>
      <SectionHeader
        icon={Server}
        title="Redis y Workers"
        description="Colas Celery y latencia de workers"
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="space-y-3 p-6">
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
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
                <p className="text-sm text-[var(--text-muted)]">Sin datos de workers.</p>
              )}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-3 p-6">
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
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
  )
}

// ---------------------------------------------------------------------------
// Storage section
// ---------------------------------------------------------------------------

export function StorageSection({
  operationsStatus,
  storageIntegrity,
}: Pick<SystemViewProps, "operationsStatus" | "storageIntegrity">) {
  return (
    <section id="storage" aria-labelledby="storage-title" className="scroll-mt-6 space-y-4">
      <h4 id="storage-title" className="sr-only">
        Disco y almacenamiento
      </h4>
      <SectionHeader
        icon={HardDrive}
        title="Disco y almacenamiento"
        description="Uso de disco e integridad de archivos"
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="space-y-4 p-6">
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
              Volúmenes montados
            </p>
            <DiskLine label="Directorio de entrada" usage={operationsStatus?.disk?.input_dir} />
            <DiskLine label="Archivos originales" usage={operationsStatus?.disk?.files_dir} />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-4 p-6">
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
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
              <MetricTile label="Huérfanos" value={String(storageIntegrity?.orphan_files ?? 0)} />
              <MetricTile
                label="Hash dudoso"
                value={String(storageIntegrity?.hash_mismatches ?? 0)}
              />
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Readiness section
// ---------------------------------------------------------------------------

export function ReadinessSection({
  productionReadiness,
  productionChecklist,
}: Pick<SystemViewProps, "productionReadiness" | "productionChecklist">) {
  return (
    <section id="readiness" aria-labelledby="readiness-title" className="scroll-mt-6 space-y-4">
      <h4 id="readiness-title" className="sr-only">
        Readiness y producción
      </h4>
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
              <Badge variant={productionReadiness?.status === "ready" ? "success" : "warning"}>
                {productionReadiness?.status ?? "sin datos"}
              </Badge>
            </div>
            <div className="grid gap-2 text-sm sm:grid-cols-2">
              {(productionReadiness?.checks ?? []).map((check) => (
                <div key={check.key} className="rounded-md border bg-[var(--bg-surface)] p-3">
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
                  <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-muted)]">
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
                <div key={item.key} className="rounded-md border bg-[var(--bg-surface)] p-3">
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
                  <p className="mt-1 text-[11px] leading-relaxed text-[var(--text-muted)]">
                    {item.description}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Access section (users + notifications)
// ---------------------------------------------------------------------------

export function AccessSection({
  adminUsers,
  notificationRules,
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
}: SystemViewProps) {
  return (
    <section id="access" aria-labelledby="access-title" className="scroll-mt-6 space-y-4">
      <h4 id="access-title" className="sr-only">
        Usuarios y notificaciones
      </h4>
      <SectionHeader
        icon={UserPlus}
        title="Usuarios y notificaciones"
        description="Cuentas admin y reglas de notificación"
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="space-y-4 p-6">
            <div className="flex items-center gap-2">
              <UserPlus className="size-4 text-[var(--text-muted)]" />
              <p className="text-sm font-medium">Crear usuario admin</p>
            </div>
            <form
              className="grid gap-2 md:grid-cols-2"
              onSubmit={(e: FormEvent) => {
                e.preventDefault()
                if (adminUserEmail.trim() && adminUserName.trim() && adminUserPassword.length >= 12)
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
              <StyledSelect
                value={adminUserRole}
                onChange={(e) => setAdminUserRole(e.target.value)}
              >
                <option value="operario">Operario</option>
                <option value="gestor">Gestor</option>
                <option value="auditor">Auditor</option>
                <option value="admin">Admin</option>
              </StyledSelect>
              <Input
                type="password"
                value={adminUserPassword}
                onChange={(e) => setAdminUserPassword(e.target.value)}
                placeholder="Contraseña (12+ caracteres)"
                className="h-9"
              />
              <div className="md:col-span-2 flex items-center justify-between gap-2">
                <p className="text-[11px] text-[var(--text-muted)]">Mínimo 12 caracteres.</p>
                <Button disabled={createAdminUser.isPending || adminUserPassword.length < 12}>
                  Crear usuario
                </Button>
              </div>
            </form>
            {createAdminUser.isError && (
              <p className="text-sm text-[var(--danger)]">{createAdminUser.error?.message}</p>
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
                        <p className="text-[10px] text-[var(--text-muted)]">{u.email}</p>
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
              <Bell className="size-4 text-[var(--text-muted)]" />
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
              <StyledSelect
                value={notificationChannel}
                onChange={(e) => setNotificationChannel(e.target.value)}
              >
                <option value="webhook">Webhook</option>
                <option value="email">Email</option>
                <option value="teams">Teams</option>
              </StyledSelect>
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
              <p className="text-sm text-[var(--danger)]">
                {createNotificationRule.error?.message}
              </p>
            )}
            <div className="space-y-2">
              {notificationRules.map((rule) => (
                <div key={rule.id} className="rounded-md border bg-[var(--bg-surface)] p-3 text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-medium">{rule.name}</p>
                    <Badge variant={rule.is_active ? "success" : "neutral"} className="text-[10px]">
                      {rule.channel}
                    </Badge>
                  </div>
                  <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                    {rule.event_type} → {rule.target}
                  </p>
                </div>
              ))}
              {!notificationRules.length && (
                <p className="text-sm text-[var(--text-muted)]">Sin reglas.</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// AI Config section
// ---------------------------------------------------------------------------

export function AiConfigSection({
  productionReadiness,
  maintenanceReport,
  stats,
  seedDemo,
}: Pick<SystemViewProps, "productionReadiness" | "maintenanceReport" | "stats" | "seedDemo">) {
  const confirm = useConfirm()

  return (
    <section id="ai-config" aria-labelledby="ai-config-title" className="scroll-mt-6 space-y-4">
      <h4 id="ai-config-title" className="sr-only">
        Configuración IA/OCR
      </h4>
      <SectionHeader
        icon={Layers}
        title="Configuración IA/OCR"
        description="Motores, dimensiones y datos de demostración"
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="space-y-4 p-6">
            <p className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
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
            <div className="rounded-md border bg-[var(--bg-surface-2)] p-3 font-mono text-[11px] leading-relaxed text-[var(--text-muted)]">
              <div>AI_PROVIDER=local_openai_compatible</div>
              <div>OCR_ENGINE=paddleocr</div>
              <div>Docs en revisión: {stats?.documents_needs_review ?? "-"}</div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-4 p-6">
            <div className="flex items-center gap-2">
              <DatabaseZap className="size-4 text-[var(--text-muted)]" />
              <p className="text-sm font-medium">Datos de demostración</p>
            </div>
            <p className="text-sm text-[var(--text-muted)]">
              Crea un conjunto reducido de documentos para mostrar el funcionamiento del sistema.
            </p>
            <div className="flex items-center gap-3">
              <Button
                type="button"
                onClick={async () => {
                  const ok = await confirm({
                    title: "¿Activar datos demo?",
                    description:
                      "Se crearán documentos de ejemplo. La operación queda registrada en la auditoría.",
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
                <span className="text-sm text-[var(--danger)]">{seedDemo.error?.message}</span>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
