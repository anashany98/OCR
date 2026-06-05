import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock,
  Eye,
  FileSearch,
  FileWarning,
  Filter,
  MessageSquare,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldAlert,
  UserRoundCheck,
  UserRoundPlus,
  XCircle,
} from "lucide-react"

import { api } from "@/api/client"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { EmptyState } from "@/components/layout/EmptyState"
import { PageHeader } from "@/components/layout/PageHeader"
import { PriorityBadge } from "@/components/layout/PriorityBadge"
import { Badge, type BadgeProps } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { workInboxTarget } from "@/lib/operations"
import { notify } from "@/lib/toast"
import type { WorkInboxItem, WorkItem } from "@/types/api"

// ---------------------------------------------------------------------------
// Task type registry
// ---------------------------------------------------------------------------
type TaskKind =
  | "ocr_failed"
  | "low_ocr"
  | "unknown_type"
  | "duplicate"
  | "quarantine"
  | "accepted_budget_without_order"
  | "order_without_budget"
  | "amount_mismatch"
  | "missing_fields"
  | "needs_human_review"
  | "failed_job"
  | "processed_low_quality"
  | "plan_without_scale"
  | string

const taskKindConfig: Record<string, { label: string; icon: React.ComponentType<{ className?: string }>; tone: string }> = {
  ocr_failed:          { label: "OCR fallido",               icon: ShieldAlert,   tone: "danger" },
  low_ocr:             { label: "OCR de baja confianza",      icon: FileWarning,   tone: "warning" },
  unknown_type:        { label: "Clasificación dudosa",       icon: FileSearch,    tone: "warning" },
  duplicate:           { label: "Duplicado detectado",        icon: FileSearch,    tone: "info" },
  quarantine:          { label: "Documento en cuarentena",    icon: ShieldAlert,   tone: "danger" },
  accepted_budget_without_order: { label: "Presupuesto aceptado sin pedido", icon: AlertTriangle, tone: "warning" },
  order_without_budget: { label: "Pedido sin presupuesto",    icon: AlertTriangle, tone: "warning" },
  amount_mismatch:     { label: "Importes no coincidentes",   icon: AlertTriangle, tone: "danger" },
  missing_fields:      { label: "Documento sin entidades clave", icon: FileWarning, tone: "warning" },
  needs_human_review:  { label: "Pendiente de validación",    icon: Eye,           tone: "info" },
  failed_job:          { label: "Job fallido",               icon: XCircle,       tone: "danger" },
  processed_low_quality: { label: "Baja calidad documental",  icon: FileWarning,   tone: "warning" },
  plan_without_scale:  { label: "Plano sin escala",          icon: FileWarning,   tone: "warning" },
}

function getKindConfig(kind: string) {
  return taskKindConfig[kind] ?? { label: kind.replace(/_/g, " "), icon: FileSearch, tone: "neutral" }
}

// ---------------------------------------------------------------------------
// Unified task item
// ---------------------------------------------------------------------------
type TaskItem = {
  id: string
  itemType: "auto" | "persisted"
  kind: string
  title: string
  description: string
  priority: string
  status: string
  documentId: number | null
  pageId: number | null
  jobId: number | null
  assigneeUserId: number | null
  createdAt: string | null
  actionUrl: string | null
  raw: WorkInboxItem | WorkItem
}

function inboxToTask(item: WorkInboxItem, index: number): TaskItem {
  return {
    id: `auto-${item.kind}-${item.document_id ?? "d"}-${item.job_id ?? "j"}-${index}`,
    itemType: "auto",
    kind: item.kind,
    title: item.title,
    description: item.description,
    priority: item.severity === "error" || item.severity === "critical" ? "critical" : item.severity === "warning" ? "high" : "normal",
    status: item.status ?? "open",
    documentId: item.document_id,
    pageId: item.page_id,
    jobId: item.job_id,
    assigneeUserId: null,
    createdAt: item.created_at,
    actionUrl: item.action_url,
    raw: item,
  }
}

function persistedToTask(item: WorkItem): TaskItem {
  return {
    id: `persisted-${item.id}`,
    itemType: "persisted",
    kind: item.kind,
    title: item.title,
    description: item.description,
    priority: item.priority,
    status: item.status,
    documentId: item.document_id,
    pageId: item.page_id,
    jobId: item.job_id,
    assigneeUserId: item.assignee_user_id,
    createdAt: item.created_at,
    actionUrl: workInboxTarget({ kind: item.kind, severity: item.priority, title: "", description: "", document_id: item.document_id, page_id: item.page_id, job_id: item.job_id, action_url: null, status: item.status, created_at: item.created_at }),
    raw: item,
  }
}

// ---------------------------------------------------------------------------
// Priority ordering
// ---------------------------------------------------------------------------
const priorityOrder: Record<string, number> = { critical: 0, high: 1, normal: 2, low: 3 }
const priorityLabels: Record<string, string> = { critical: "Críticas", high: "Altas", normal: "Normales", low: "Bajas" }

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export function WorkInboxPage() {
  const queryClient = useQueryClient()
  const [kindFilter, setKindFilter] = useState<string>("")
  const [priorityFilter, setPriorityFilter] = useState<string>("")
  const [searchTerm, setSearchTerm] = useState("")
  const [newTaskTitle, setNewTaskTitle] = useState("")
  const [newTaskPriority, setNewTaskPriority] = useState("normal")
  const [commentText, setCommentText] = useState<Record<number, string>>({})
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set(["critical", "high", "normal", "low"]))

  const inbox = useQuery({ queryKey: ["work-inbox"], queryFn: () => api.workInbox({ limit: 200 }), refetchInterval: 10000 })
  const persisted = useQuery({ queryKey: ["work-items"], queryFn: () => api.workItems({ limit: 100 }), refetchInterval: 15000 })
  const action = useMutation({
    mutationFn: api.runWorkInboxAction,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["work-inbox"] })
      queryClient.invalidateQueries({ queryKey: ["jobs"] })
      queryClient.invalidateQueries({ queryKey: ["ocr-review"] })
      queryClient.invalidateQueries({ queryKey: ["operations-overview"] })
      notify.success(
        "Acción en lote completada",
        `${data.updated} actualizados, ${data.enqueued} encolados.`,
      )
    },
    onError: (err) => notify.error(err, "No se pudo ejecutar la acción en lote"),
  })
  const createTask = useMutation({
    mutationFn: () =>
      api.createWorkItem({
        kind: "manual",
        title: newTaskTitle.trim(),
        description: "Tarea manual creada desde el centro de trabajo.",
        priority: newTaskPriority,
      }),
    onSuccess: () => {
      setNewTaskTitle("")
      queryClient.invalidateQueries({ queryKey: ["work-items"] })
      notify.success("Tarea creada")
    },
    onError: (err) => notify.error(err, "No se pudo crear la tarea"),
  })
  const updateTask = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      api.updateWorkItem(id, { status, resolution_notes: status === "resolved" ? "Resuelta desde centro de trabajo" : null }),
    onSuccess: (_, vars) => {
      queryClient.invalidateQueries({ queryKey: ["work-items"] })
      const label = vars.status === "resolved" ? "resuelta" : vars.status === "ignored" ? "ignorada" : "actualizada"
      notify.success(`Tarea ${label}`)
    },
    onError: (err) => notify.error(err, "No se pudo actualizar la tarea"),
  })
  const addComment = useMutation({
    mutationFn: ({ id, body }: { id: number; body: string }) => api.addWorkItemComment(id, { body }),
    onSuccess: (_, variables) => {
      setCommentText((current) => ({ ...current, [variables.id]: "" }))
      queryClient.invalidateQueries({ queryKey: ["work-items"] })
    },
    onError: (err) => notify.error(err, "No se pudo añadir el comentario"),
  })

  // Build unified task list
  const autoTasks: TaskItem[] = (inbox.data ?? []).map(inboxToTask)
  const persistedTasks: TaskItem[] = (persisted.data ?? []).filter((w) => w.status !== "resolved").map(persistedToTask)
  const allTasks = [...autoTasks, ...persistedTasks]

  // Filter tasks
  const filteredTasks = allTasks.filter((task) => {
    if (kindFilter && task.kind !== kindFilter) return false
    if (priorityFilter && task.priority !== priorityFilter) return false
    if (searchTerm) {
      const q = searchTerm.toLowerCase()
      if (!task.title.toLowerCase().includes(q) && !task.description.toLowerCase().includes(q)) return false
    }
    return true
  })

  // Group by priority
  const grouped = groupByPriority(filteredTasks)
  const priorityKeys = Object.keys(priorityOrder).filter((key) => grouped[key]?.length > 0)

  // Available kinds for filter dropdown
  const availableKinds = Array.from(new Set(allTasks.map((t) => t.kind))).sort()

  // Counts
  const critical = allTasks.filter((t) => t.priority === "critical").length
  const high = allTasks.filter((t) => t.priority === "high").length
  const open = autoTasks.filter((t) => t.status === "open").length
  const persistedOpen = persistedTasks.length

  return (
    <>
      <Breadcrumbs items={[{ label: "Tareas" }]} />
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
        <PageHeader title="Tareas" description="Centro de trabajo diario. Gestiona incidencias, revisa documentos y resuelve tareas por prioridad." />
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => inbox.refetch()} disabled={inbox.isFetching}>
            <RefreshCw className="h-3.5 w-3.5" />
            <span className="ml-1.5 hidden sm:inline">Actualizar</span>
          </Button>
        </div>
      </div>

      {/* Priority summary cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          label="Críticas"
          count={critical}
          icon={ShieldAlert}
          tone="danger"
          active={expandedGroups.has("critical")}
          onClick={() => toggleGroup("critical")}
        />
        <SummaryCard
          label="Prioridad alta"
          count={high}
          icon={AlertTriangle}
          tone="warning"
          active={expandedGroups.has("high")}
          onClick={() => toggleGroup("high")}
        />
        <SummaryCard
          label="Pendientes auto"
          count={open}
          icon={Clock}
          tone="info"
          active={expandedGroups.has("normal")}
          onClick={() => toggleGroup("normal")}
        />
        <SummaryCard
          label="Tareas manuales"
          count={persistedOpen}
          icon={UserRoundCheck}
          tone="neutral"
          active={expandedGroups.has("low")}
          onClick={() => toggleGroup("low")}
        />
      </div>

      {/* Main content */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        {/* Left: task list by priority */}
        <div className="space-y-4">
          {/* Filters toolbar */}
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] bg-white p-2">
            <Filter className="ml-1 h-3.5 w-3.5 text-[var(--text-muted)]" />
            <select
              className="h-8 rounded-md border bg-background px-2 text-xs"
              value={kindFilter}
              onChange={(e) => setKindFilter(e.target.value)}
            >
              <option value="">Todos los tipos</option>
              {availableKinds.map((kind) => (
                <option key={kind} value={kind}>{getKindConfig(kind).label}</option>
              ))}
            </select>
            <select
              className="h-8 rounded-md border bg-background px-2 text-xs"
              value={priorityFilter}
              onChange={(e) => setPriorityFilter(e.target.value)}
            >
              <option value="">Todas las prioridades</option>
              <option value="critical">Críticas</option>
              <option value="high">Altas</option>
              <option value="normal">Normales</option>
              <option value="low">Bajas</option>
            </select>
            <div className="relative flex-1 min-w-[160px]">
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--text-muted)]" />
              <Input
                className="h-8 pl-7 text-xs"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Buscar tarea..."
              />
            </div>
            {(kindFilter || priorityFilter || searchTerm) && (
              <Button
                variant="ghost"
                size="sm"
                className="h-8 text-xs text-[var(--text-muted)]"
                onClick={() => { setKindFilter(""); setPriorityFilter(""); setSearchTerm("") }}
              >
                Limpiar filtros
              </Button>
            )}
          </div>

          {/* Tasks grouped by priority */}
          {priorityKeys.length === 0 ? (
            <Card>
              <CardContent className="py-8">
                <EmptyState
                  title="Sin tareas pendientes"
                  description="No hay incidencias abiertas que requieran atención. ¡Buen trabajo!"
                  icon={<CheckCircle2 className="h-8 w-8 text-[var(--emerald)]" />}
                />
              </CardContent>
            </Card>
          ) : (
            priorityKeys.map((priority) => (
              <PriorityGroup
                key={priority}
                priority={priority}
                tasks={grouped[priority]}
                expanded={expandedGroups.has(priority)}
                onToggle={() => toggleGroup(priority)}
                onUpdateTask={(id, status) => updateTask.mutate({ id, status })}
                commentText={commentText}
                onCommentChange={(id, text) => setCommentText((prev) => ({ ...prev, [id]: text }))}
                onAddComment={(id, body) => addComment.mutate({ id, body })}
                isUpdating={updateTask.isPending}
                isCommenting={addComment.isPending}
              />
            ))
          )}
        </div>

        {/* Right column */}
        <div className="space-y-4">
          {/* New manual task */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px]">Nueva tarea manual</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <form
                className="grid gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (newTaskTitle.trim()) createTask.mutate()
                }}
              >
                <Input
                  value={newTaskTitle}
                  onChange={(e) => setNewTaskTitle(e.target.value)}
                  placeholder="Describe la tarea..."
                  className="h-9"
                />
                <div className="flex gap-2">
                  <select
                    className="h-9 flex-1 rounded-md border bg-background px-3 text-sm"
                    value={newTaskPriority}
                    onChange={(e) => setNewTaskPriority(e.target.value)}
                  >
                    <option value="normal">Normal</option>
                    <option value="high">Alta</option>
                    <option value="critical">Crítica</option>
                    <option value="low">Baja</option>
                  </select>
                  <Button size="sm" disabled={createTask.isPending || !newTaskTitle.trim()} className="gap-1">
                    <Plus className="h-3.5 w-3.5" />
                    Crear
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>

          {/* Batch actions */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px]">Acciones en lote</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <Button
                variant="outline"
                size="sm"
                className="w-full justify-start"
                onClick={() => action.mutate({ action: "retry_failed_jobs", limit: 100 })}
                disabled={action.isPending}
              >
                <RotateCcw className="mr-2 h-3.5 w-3.5" />
                Reintentar jobs fallidos
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="w-full justify-start"
                onClick={() => action.mutate({ action: "approve_high_confidence_ocr", min_confidence: 0.85, limit: 200 })}
                disabled={action.isPending}
              >
                <CheckCircle2 className="mr-2 h-3.5 w-3.5" />
                Aprobar OCR fiable
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="w-full justify-start"
                onClick={() => action.mutate({ action: "reprocess_low_quality", limit: 100 })}
                disabled={action.isPending}
              >
                <FileWarning className="mr-2 h-3.5 w-3.5" />
                Reprocesar baja calidad
              </Button>
              {action.data && (
                <p className="rounded-md border bg-slate-50 p-2 text-xs text-muted-foreground">
                  Encontrados: {action.data.matched}. Actualizados: {action.data.updated}. Encolados: {action.data.enqueued}.
                </p>
              )}
              {action.isError && <p className="text-xs text-destructive">{action.error.message}</p>}
            </CardContent>
          </Card>

          {/* Kind summary */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px]">Resumen por tipo</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {Object.entries(countByKind(allTasks)).map(([kind, count]) => {
                const cfg = getKindConfig(kind)
                return (
                  <button
                    key={kind}
                    type="button"
                    className={cn(
                      "flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-colors hover:bg-slate-50",
                      kindFilter === kind && "border-[var(--primary)] bg-[var(--primary-light)]",
                    )}
                    onClick={() => setKindFilter(kindFilter === kind ? "" : kind)}
                  >
                    <span className="flex items-center gap-2">
                      <cfg.icon className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                      <span>{cfg.label}</span>
                    </span>
                    <Badge variant="outline">{count}</Badge>
                  </button>
                )
              })}
              {Object.keys(countByKind(allTasks)).length === 0 && (
                <p className="text-sm text-muted-foreground">Sin incidencias abiertas.</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )

  function toggleGroup(priority: string) {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(priority)) next.delete(priority)
      else next.add(priority)
      return next
    })
  }
}

// ---------------------------------------------------------------------------
// Summary card
// ---------------------------------------------------------------------------
function SummaryCard({
  label,
  count,
  icon: Icon,
  tone,
  active,
  onClick,
}: {
  label: string
  count: number
  icon: React.ComponentType<{ className?: string }>
  tone: string
  active: boolean
  onClick: () => void
}) {
  const bgMap: Record<string, string> = {
    danger: "border-[var(--rose-light)] bg-[var(--rose-light)]/30",
    warning: "border-[var(--amber-light)] bg-[var(--amber-light)]/30",
    info: "border-[var(--sky-light)] bg-[var(--sky-light)]/30",
    neutral: "border-[var(--border)] bg-white",
  }
  const iconMap: Record<string, string> = {
    danger: "text-[var(--rose)]",
    warning: "text-[var(--amber)]",
    info: "text-[var(--sky)]",
    neutral: "text-[var(--text-muted)]",
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-3 rounded-lg border p-3 text-left transition-all hover:shadow-sm",
        bgMap[tone] ?? bgMap.neutral,
        active ? "ring-1 ring-[var(--primary)]" : "",
      )}
    >
      <Icon className={cn("h-5 w-5", iconMap[tone] ?? iconMap.neutral)} />
      <div>
        <p className="text-2xl font-bold text-[var(--text-primary)]">{count}</p>
        <p className="text-xs text-[var(--text-muted)]">{label}</p>
      </div>
    </button>
  )
}

// ---------------------------------------------------------------------------
// Priority group
// ---------------------------------------------------------------------------
function PriorityGroup({
  priority,
  tasks,
  expanded,
  onToggle,
  onUpdateTask,
  commentText,
  onCommentChange,
  onAddComment,
  isUpdating,
  isCommenting,
}: {
  priority: string
  tasks: TaskItem[]
  expanded: boolean
  onToggle: () => void
  onUpdateTask: (id: number, status: string) => void
  commentText: Record<number, string>
  onCommentChange: (id: number, text: string) => void
  onAddComment: (id: number, body: string) => void
  isUpdating: boolean
  isCommenting: boolean
}) {
  const bgMap: Record<string, string> = {
    critical: "border-l-[var(--rose)]",
    high: "border-l-[var(--amber)]",
    normal: "border-l-[var(--sky)]",
    low: "border-l-[var(--border-2)]",
  }

  return (
    <Card className={cn("overflow-hidden border-l-4", bgMap[priority] ?? bgMap.normal)}>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between px-5 py-3 hover:bg-slate-50/80"
      >
        <div className="flex items-center gap-3">
          <PriorityBadge priority={priority} />
          <span className="text-[13px] font-medium text-[var(--text-secondary)]">
            {priorityLabels[priority] ?? priority}
          </span>
          <Badge variant="outline" className="text-[11px]">{tasks.length}</Badge>
        </div>
        <ArrowRight className={cn("h-4 w-4 text-[var(--text-muted)] transition-transform duration-200", expanded && "rotate-90")} />
      </button>

      {expanded && (
        <div className="divide-y divide-[var(--border)] border-t border-[var(--border)]">
          {tasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              onUpdateTask={onUpdateTask}
              commentText={commentText}
              onCommentChange={onCommentChange}
              onAddComment={onAddComment}
              isUpdating={isUpdating}
              isCommenting={isCommenting}
            />
          ))}
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Task row
// ---------------------------------------------------------------------------
function TaskRow({
  task,
  onUpdateTask,
  commentText,
  onCommentChange,
  onAddComment,
  isUpdating,
  isCommenting,
}: {
  task: TaskItem
  onUpdateTask: (id: number, status: string) => void
  commentText: Record<number, string>
  onCommentChange: (id: number, text: string) => void
  onAddComment: (id: number, body: string) => void
  isUpdating: boolean
  isCommenting: boolean
}) {
  const cfg = getKindConfig(task.kind)
  const KindIcon = cfg.icon
  const isPersisted = task.itemType === "persisted"
  const persistedId = isPersisted ? (task.raw as WorkItem).id : 0

  return (
    <div className="group px-5 py-3 transition-colors hover:bg-slate-50/60">
      <div className="flex items-start justify-between gap-4">
        {/* Left: type + title + meta */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1.5">
            <KindIcon className={cn("h-3.5 w-3.5 flex-shrink-0", {
              "text-[var(--rose)]": cfg.tone === "danger",
              "text-[var(--amber)]": cfg.tone === "warning",
              "text-[var(--sky)]": cfg.tone === "info",
              "text-[var(--text-muted)]": cfg.tone === "neutral",
            })} />
            <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wide">{cfg.label}</span>
            {task.itemType === "auto" && (
              <Badge variant="neutral" className="text-[10px] px-1.5 py-0">Auto</Badge>
            )}
            {task.status && task.status !== "open" && (
              <Badge variant="info" className="text-[10px] px-1.5 py-0">{task.status.replace(/_/g, " ")}</Badge>
            )}
          </div>
          <p className="text-[13px] font-medium text-[var(--text-primary)] mb-1">{task.title}</p>
          <p className="text-[12px] text-[var(--text-muted)] line-clamp-2">{task.description}</p>

          {/* Meta row */}
          <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-[var(--text-muted)]">
            {task.documentId && (
              <Link
                to={`/documents/${task.documentId}`}
                className="inline-flex items-center gap-1 text-[var(--sky)] hover:underline"
              >
                <FileSearch className="h-3 w-3" />
                Doc #{task.documentId}
              </Link>
            )}
            {task.pageId && (
              <span>Página {task.pageId}</span>
            )}
            {task.jobId && (
              <Link to="/jobs" className="text-[var(--sky)] hover:underline">
                Job #{task.jobId}
              </Link>
            )}
            {task.assigneeUserId && (
              <span className="inline-flex items-center gap-1">
                <UserRoundCheck className="h-3 w-3" />
                Asignado a #{task.assigneeUserId}
              </span>
            )}
            {task.createdAt && (
              <span className="inline-flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {new Date(task.createdAt).toLocaleDateString("es-ES", { day: "numeric", month: "short" })}
              </span>
            )}
            {isPersisted && (task.raw as WorkItem).comments.length > 0 && (
              <span className="inline-flex items-center gap-1">
                <MessageSquare className="h-3 w-3" />
                {(task.raw as WorkItem).comments.length}
              </span>
            )}
          </div>
        </div>

        {/* Right: actions */}
        <div className="flex flex-col items-end gap-2 flex-shrink-0">
          {task.documentId ? (
            <Button asChild variant="outline" size="sm" className="h-7 text-xs">
              <Link to={`/documents/${task.documentId}`}>
                <Eye className="h-3 w-3 mr-1" />
                Revisar
              </Link>
            </Button>
          ) : task.itemType === "auto" ? (
            <Button
              asChild
              variant="outline"
              size="sm"
              className="h-7 text-xs"
            >
              <Link to={task.actionUrl ?? "/"}>
                <ArrowRight className="h-3 w-3 mr-1" />
                Abrir
              </Link>
            </Button>
          ) : null}

          {isPersisted && (
            <div className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
              {/* Comment */}
              <div className="flex items-center gap-1">
                <Input
                  className="h-7 w-24 text-xs"
                  value={commentText[persistedId] ?? ""}
                  onChange={(e) => onCommentChange(persistedId, e.target.value)}
                  placeholder="Comentario"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  disabled={!commentText[persistedId]?.trim() || isCommenting}
                  onClick={() => onAddComment(persistedId, commentText[persistedId].trim())}
                  title="Comentar"
                >
                  <MessageSquare className="h-3.5 w-3.5" />
                </Button>
              </div>
              {/* Resolve */}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-[var(--emerald)]"
                disabled={isUpdating || task.status === "resolved"}
                onClick={() => onUpdateTask(persistedId, "resolved")}
                title="Resolver"
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
              </Button>
              {/* Ignore */}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-[var(--text-muted)]"
                disabled={isUpdating || task.status === "ignored"}
                onClick={() => onUpdateTask(persistedId, "ignored")}
                title="Ignorar"
              >
                <XCircle className="h-3.5 w-3.5" />
              </Button>
              {/* Assign */}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-[var(--sky)]"
                title="Asignar"
              >
                <UserRoundPlus className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function groupByPriority(tasks: TaskItem[]): Record<string, TaskItem[]> {
  const groups: Record<string, TaskItem[]> = { critical: [], high: [], normal: [], low: [] }
  for (const task of tasks) {
    const p = task.priority in groups ? task.priority : "normal"
    groups[p].push(task)
  }
  return groups
}

function countByKind(tasks: TaskItem[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const task of tasks) {
    counts[task.kind] = (counts[task.kind] ?? 0) + 1
  }
  return counts
}
