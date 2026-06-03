import type { FormEvent } from "react"
import {
  BellRing,
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
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

import { ConfigStatus, DiskLine, MetricBlock, MetricTile } from "./shared"

interface MutationLike<TData = unknown> {
  mutate: () => void
  isPending: boolean; data?: TData; isError: boolean; error: Error | null
}
interface ToggleMutation { mutate: (args: { id: number; is_active: boolean }) => void; isPending: boolean }

interface AdminSystemTabProps {
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
  adminUserEmail: string; setAdminUserEmail: (v: string) => void
  adminUserName: string; setAdminUserName: (v: string) => void
  adminUserRole: string; setAdminUserRole: (v: string) => void
  adminUserPassword: string; setAdminUserPassword: (v: string) => void
  createAdminUser: MutationLike; toggleAdminUser: ToggleMutation
  notificationName: string; setNotificationName: (v: string) => void
  notificationEventType: string; setNotificationEventType: (v: string) => void
  notificationChannel: string; setNotificationChannel: (v: string) => void
  notificationTarget: string; setNotificationTarget: (v: string) => void
  createNotificationRule: MutationLike
  seedDemo: MutationLike<{ seeded: boolean }>
}

export function AdminSystemTab(props: AdminSystemTabProps) {
  const {
    systemHealth, productionChecklist, productionReadiness, maintenanceReport, storageIntegrity,
    adminUsers, notificationRules, operationsStatus, queueStatus, operationsOverview, stats,
    adminUserEmail, setAdminUserEmail, adminUserName, setAdminUserName, adminUserRole, setAdminUserRole, adminUserPassword, setAdminUserPassword,
    createAdminUser, toggleAdminUser,
    notificationName, setNotificationName, notificationEventType, setNotificationEventType,
    notificationChannel, setNotificationChannel, notificationTarget, setNotificationTarget,
    createNotificationRule, seedDemo,
  } = props

  return (
    <div className="space-y-6">
      {/* ── Base de datos ── */}
      <SectionHeader icon={Database} title="PostgreSQL" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="pt-4">
            <div className="flex flex-wrap gap-2">
              <Badge variant={systemHealth?.status === "ok" ? "success" : "warning"}>{systemHealth?.status ?? "sin datos"}</Badge>
              {Object.entries(systemHealth?.checks ?? {}).filter(([k]) => k === "database" || k === "postgresql").map(([key, check]) => (
                <Badge key={key} variant={check.status === "ok" ? "outline" : "warning"}>{key}: {check.status}</Badge>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <ConfigStatus label="Estado" value={systemHealth?.status === "ok" ? "operativo" : "degradado"} tone={systemHealth?.status === "ok" ? "success" : "warning"} />
          </CardContent>
        </Card>
      </div>

      {/* ── Redis y Celery ── */}
      <SectionHeader icon={Server} title="Redis y Workers" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="pt-4">
            <div className="flex flex-wrap gap-2">
              {Object.entries(systemHealth?.checks ?? {}).filter(([k]) => k === "redis" || k === "celery" || k === "worker").map(([key, check]) => (
                <Badge key={key} variant={check.status === "ok" ? "success" : check.status === "warning" ? "warning" : "danger"}>
                  {key}: {check.status}
                </Badge>
              ))}
              {Object.keys(systemHealth?.checks ?? {}).filter((k) => k === "redis" || k === "celery" || k === "worker").length === 0 && (
                <p className="text-sm text-muted-foreground">Sin datos de workers.</p>
              )}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 text-sm">
            <MetricBlock title="Colas por tipo" values={queueStatus?.queues ? Object.fromEntries(Object.entries(queueStatus.queues).map(([k, v]) => [k, v.pending ?? 0])) : undefined} />
          </CardContent>
        </Card>
      </div>

      {/* ── Disco ── */}
      <SectionHeader icon={HardDrive} title="Disco y almacenamiento" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="space-y-3 pt-4 text-sm">
            <DiskLine label="Directorio de entrada" usage={operationsStatus?.disk?.input_dir} />
            <DiskLine label="Archivos originales" usage={operationsStatus?.disk?.files_dir} />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-2 pt-4 text-sm">
            <p className="text-xs text-muted-foreground">Integridad de almacenamiento</p>
            <div className="grid grid-cols-2 gap-2">
              <MetricTile label="Comprobados" value={String(storageIntegrity?.checked_documents ?? 0)} />
              <MetricTile label="Sin fichero" value={String(storageIntegrity?.missing_files ?? 0)} />
              <MetricTile label="Huérfanos" value={String(storageIntegrity?.orphan_files ?? 0)} />
              <MetricTile label="Hash dudoso" value={String(storageIntegrity?.hash_mismatches ?? 0)} />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Readiness y backups ── */}
      <SectionHeader icon={ShieldCheck} title="Readiness y producción" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="pt-4">
            <div className="mb-3 flex items-center gap-2">
              <p className="text-sm font-medium">Readiness productivo</p>
              <Badge variant={productionReadiness?.status === "ready" ? "success" : "warning"}>{productionReadiness?.status ?? "sin datos"}</Badge>
            </div>
            <div className="grid gap-2 text-sm sm:grid-cols-2">
              {(productionReadiness?.checks ?? []).map((check) => (
                <div key={check.key} className="rounded-md border p-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-medium">{check.key}</p>
                    <Badge variant={check.status === "ok" ? "success" : check.status === "error" ? "destructive" : "warning"}>{check.status}</Badge>
                  </div>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{check.description}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <p className="mb-2 text-sm font-medium">Checklist producción</p>
            <div className="grid gap-2 text-sm sm:grid-cols-2">
              {(productionChecklist?.items ?? []).map((item) => (
                <div key={item.key} className="rounded-md border p-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs font-medium">{item.title}</p>
                    <Badge variant={item.status === "ok" ? "success" : item.status === "error" ? "destructive" : "warning"}>{item.status}</Badge>
                  </div>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">{item.description}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Usuarios y notificaciones ── */}
      <SectionHeader icon={UserPlus} title="Usuarios y notificaciones" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="space-y-4 pt-4">
            <form className="grid gap-2 md:grid-cols-[1fr_1fr_120px_140px_auto]" onSubmit={(e: FormEvent) => { e.preventDefault(); if (adminUserEmail.trim() && adminUserName.trim() && adminUserPassword.length >= 12) createAdminUser.mutate() }}>
              <Input value={adminUserEmail} onChange={(e) => setAdminUserEmail(e.target.value)} placeholder="email@empresa.com" className="h-9" />
              <Input value={adminUserName} onChange={(e) => setAdminUserName(e.target.value)} placeholder="Nombre" className="h-9" />
              <select className="h-9 rounded-md border bg-background px-2 text-sm" value={adminUserRole} onChange={(e) => setAdminUserRole(e.target.value)}>
                <option value="operario">Operario</option>
                <option value="gestor">Gestor</option>
                <option value="auditor">Auditor</option>
                <option value="admin">Admin</option>
              </select>
              <Input type="password" value={adminUserPassword} onChange={(e) => setAdminUserPassword(e.target.value)} placeholder="Contraseña" className="h-9" />
              <Button disabled={createAdminUser.isPending || adminUserPassword.length < 12}>Crear</Button>
            </form>
            <div className="max-h-[240px] overflow-auto rounded-md border">
              <Table>
                <TableHeader><TableRow><TableHead className="text-xs">Usuario</TableHead><TableHead className="text-xs">Rol</TableHead><TableHead className="text-xs">Estado</TableHead><TableHead className="text-xs" /></TableRow></TableHeader>
                <TableBody>
                  {adminUsers.map((u) => (
                    <TableRow key={u.id}>
                      <TableCell><p className="text-xs font-medium">{u.name}</p><p className="text-[10px] text-muted-foreground">{u.email}</p></TableCell>
                      <TableCell><Badge variant="outline" className="text-[10px]">{u.role}</Badge></TableCell>
                      <TableCell><Badge variant={u.is_active ? "success" : "neutral"} className="text-[10px]">{u.is_active ? "activo" : "inactivo"}</Badge></TableCell>
                      <TableCell><Button type="button" variant="outline" size="sm" className="h-7 text-xs" onClick={() => toggleAdminUser.mutate({ id: u.id, is_active: !u.is_active })}>{u.is_active ? "Desactivar" : "Activar"}</Button></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {createAdminUser.isError && <p className="text-sm text-destructive">{createAdminUser.error?.message}</p>}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-4 pt-4">
            <form className="grid gap-2 md:grid-cols-[1fr_100px_100px_1fr_auto]" onSubmit={(e: FormEvent) => { e.preventDefault(); if (notificationName.trim() && notificationTarget.trim()) createNotificationRule.mutate() }}>
              <Input value={notificationName} onChange={(e) => setNotificationName(e.target.value)} placeholder="Nombre regla" className="h-9" />
              <Input value={notificationEventType} onChange={(e) => setNotificationEventType(e.target.value)} placeholder="Evento" className="h-9" />
              <select className="h-9 rounded-md border bg-background px-2 text-sm" value={notificationChannel} onChange={(e) => setNotificationChannel(e.target.value)}>
                <option value="webhook">Webhook</option>
                <option value="email">Email</option>
                <option value="teams">Teams</option>
              </select>
              <Input value={notificationTarget} onChange={(e) => setNotificationTarget(e.target.value)} placeholder="URL o email" className="h-9" />
              <Button disabled={createNotificationRule.isPending}>Crear</Button>
            </form>
            <div className="space-y-2">
              {notificationRules.map((rule) => (
                <div key={rule.id} className="rounded-md border p-2 text-sm">
                  <div className="flex items-center justify-between"><p className="text-xs font-medium">{rule.name}</p><Badge variant={rule.is_active ? "success" : "neutral"} className="text-[10px]">{rule.channel}</Badge></div>
                  <p className="mt-1 text-[11px] text-muted-foreground">{rule.event_type} → {rule.target}</p>
                </div>
              ))}
              {!notificationRules.length && <p className="text-sm text-muted-foreground">Sin reglas.</p>}
            </div>
            {createNotificationRule.isError && <p className="text-sm text-destructive">{createNotificationRule.error?.message}</p>}
          </CardContent>
        </Card>
      </div>

      {/* ── Configuración ── */}
      <SectionHeader icon={Layers} title="Configuración IA/OCR" />
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardContent className="space-y-3 pt-4">
            <div className="grid gap-2 sm:grid-cols-4">
              <ConfigStatus label="Readiness" value={productionReadiness?.status ?? "-"} tone={productionReadiness?.status === "ready" ? "success" : "warning"} />
              <ConfigStatus label="OCR" value="paddleocr" tone="neutral" />
              <ConfigStatus label="Embeddings" value="backend" tone="neutral" />
              <ConfigStatus label="Backups" value={maintenanceReport ? "auditable" : "sin datos"} tone={maintenanceReport ? "success" : "warning"} />
            </div>
            <div className="grid gap-1 text-xs text-muted-foreground">
              <span>AI_PROVIDER=local_openai_compatible</span>
              <span>OCR_ENGINE=paddleocr</span>
              <span>Docs en revisión: {stats?.documents_needs_review ?? "-"}</span>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex flex-wrap items-center gap-3 rounded-md border bg-slate-50 p-3">
              <Button type="button" onClick={() => { if (window.confirm("¿Activar datos demo?")) seedDemo.mutate() }} disabled={seedDemo.isPending}>
                <DatabaseZap data-icon="inline-start" />Activar demo
              </Button>
              <span className="text-sm text-muted-foreground">Crea datos de ejemplo para demo.</span>
              {seedDemo.data && <Badge variant="success">Demo preparado</Badge>}
              {seedDemo.isError && <span className="text-sm text-destructive">{seedDemo.error?.message}</span>}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function SectionHeader({ icon: Icon, title }: { icon: React.ComponentType<{ className?: string }>; title: string }) {
  return (
    <div className="flex items-center gap-2 pt-2">
      <Icon className="h-4 w-4 text-[var(--primary)]" />
      <h3 className="text-[13px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{title}</h3>
      <div className="h-px flex-1 bg-[var(--border)]" />
    </div>
  )
}
