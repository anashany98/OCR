import { type FormEvent, useState } from "react"
import { Link } from "react-router-dom"
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
  RotateCcw,
  Search,
  ShieldAlert,
  UserRoundCheck,
  UserRoundPlus,
  XCircle,
  type LucideIcon,
} from "lucide-react"

import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { EmptyState } from "@/components/layout/EmptyState"
import { PageHeader } from "@/components/layout/PageHeader"
import { PriorityBadge } from "@/components/layout/PriorityBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import type { WorkItem } from "@/types/api"

import {
  getKindConfig,
  PRIORITY_LABELS,
  type TaskItem,
} from "./useWorkInbox"

// ---------------------------------------------------------------------------
// ICON_MAP: maps the string icon name stored in ``getKindConfig`` to a
// Lucide component. Centralised here so the configuration table
// stays JSON-serialisable.
// ---------------------------------------------------------------------------
const ICON_MAP: Record<string, LucideIcon> = {
  ShieldAlert,
  FileWarning,
  FileSearch,
  AlertTriangle,
  Eye,
  XCircle,
}

// ---------------------------------------------------------------------------
// TopBar
// ---------------------------------------------------------------------------
export function WorkInboxTopBar({
  inbox,
  onRefresh,
}: {
  inbox: { isFetching: boolean; refetch: () => void }
  onRefresh?: () => void
}) {
  return (
    <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
      <PageHeader
        title="Tareas"
        description="Centro de trabajo diario. Gestiona incidencias, revisa documentos y resuelve tareas por prioridad."
      />
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onRefresh?.() ?? inbox.refetch()}
          disabled={inbox.isFetching}
        >
          <RotateCcw className="h-3.5 w-3.5" />
          <span className="ml-1.5 hidden sm:inline">Actualizar</span>
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Breadcrumbs wrapper (just so the page doesn't need the lucide import)
// ---------------------------------------------------------------------------
export function WorkInboxBreadcrumbs() {
  return <Breadcrumbs items={[{ label: "Tareas" }]} />
}

// ---------------------------------------------------------------------------
// SummaryCard
// ---------------------------------------------------------------------------
export function SummaryCard({
  label,
  count,
  icon,
  tone,
  active,
  onClick,
}: {
  label: string
  count: number
  icon: LucideIcon
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
  const Icon = icon
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

export function WorkInboxSummaryCards({
  counts,
  expandedGroups,
  toggleGroup,
}: {
  counts: { critical: number; high: number; open: number; persisted: number }
  expandedGroups: Set<string>
  toggleGroup: (p: string) => void
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <SummaryCard
        label="Críticas"
        count={counts.critical}
        icon={ShieldAlert}
        tone="danger"
        active={expandedGroups.has("critical")}
        onClick={() => toggleGroup("critical")}
      />
      <SummaryCard
        label="Prioridad alta"
        count={counts.high}
        icon={AlertTriangle}
        tone="warning"
        active={expandedGroups.has("high")}
        onClick={() => toggleGroup("high")}
      />
      <SummaryCard
        label="Pendientes auto"
        count={counts.open}
        icon={Clock}
        tone="info"
        active={expandedGroups.has("normal")}
        onClick={() => toggleGroup("normal")}
      />
      <SummaryCard
        label="Tareas manuales"
        count={counts.persisted}
        icon={UserRoundCheck}
        tone="neutral"
        active={expandedGroups.has("low")}
        onClick={() => toggleGroup("low")}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// FiltersToolbar
// ---------------------------------------------------------------------------
export function WorkInboxFiltersToolbar({
  kindFilter,
  setKindFilter,
  priorityFilter,
  setPriorityFilter,
  searchTerm,
  setSearchTerm,
  availableKinds,
  onClear,
}: {
  kindFilter: string
  setKindFilter: (v: string) => void
  priorityFilter: string
  setPriorityFilter: (v: string) => void
  searchTerm: string
  setSearchTerm: (v: string) => void
  availableKinds: string[]
  onClear: () => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] bg-white p-2">
      <Filter className="ml-1 h-3.5 w-3.5 text-[var(--text-muted)]" />
      <select
        className="h-8 rounded-md border bg-background px-2 text-xs"
        value={kindFilter}
        onChange={(e) => setKindFilter(e.target.value)}
      >
        <option value="">Todos los tipos</option>
        {availableKinds.map((kind) => (
          <option key={kind} value={kind}>
            {getKindConfig(kind).label}
          </option>
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
      <div className="relative min-w-[160px] flex-1">
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
          onClick={onClear}
        >
          Limpiar filtros
        </Button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// PriorityGroup + TaskRow
// ---------------------------------------------------------------------------
export function PriorityGroup({
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
            {PRIORITY_LABELS[priority] ?? priority}
          </span>
          <Badge variant="outline" className="text-[11px]">
            {tasks.length}
          </Badge>
        </div>
        <ArrowRight
          className={cn(
            "h-4 w-4 text-[var(--text-muted)] transition-transform duration-200",
            expanded && "rotate-90",
          )}
        />
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

export function TaskRow({
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
  const KindIcon = ICON_MAP[cfg.icon] ?? FileSearch
  const isPersisted = task.itemType === "persisted"
  const persistedId = isPersisted ? (task.raw as WorkItem).id : 0
  return (
    <div className="group px-5 py-3 transition-colors hover:bg-slate-50/60">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex items-center gap-2">
            <KindIcon
              className={cn("h-3.5 w-3.5 flex-shrink-0", {
                "text-[var(--rose)]": cfg.tone === "danger",
                "text-[var(--amber)]": cfg.tone === "warning",
                "text-[var(--sky)]": cfg.tone === "info",
                "text-[var(--text-muted)]": cfg.tone === "neutral",
              })}
            />
            <span className="text-xs font-medium uppercase tracking-wide text-[var(--text-muted)]">
              {cfg.label}
            </span>
            {task.itemType === "auto" && (
              <Badge variant="neutral" className="px-1.5 py-0 text-[10px]">
                Auto
              </Badge>
            )}
            {task.status && task.status !== "open" && (
              <Badge variant="info" className="px-1.5 py-0 text-[10px]">
                {task.status.replace(/_/g, " ")}
              </Badge>
            )}
          </div>
          <p className="mb-1 text-[13px] font-medium text-[var(--text-primary)]">{task.title}</p>
          <p className="line-clamp-2 text-[12px] text-[var(--text-muted)]">{task.description}</p>
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
            {task.pageId && <span>Página {task.pageId}</span>}
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
                {new Date(task.createdAt).toLocaleDateString("es-ES", {
                  day: "numeric",
                  month: "short",
                })}
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
        <div className="flex flex-shrink-0 flex-col items-end gap-2">
          {task.documentId ? (
            <Button asChild variant="outline" size="sm" className="h-7 text-xs">
              <Link to={`/documents/${task.documentId}`}>
                <Eye className="mr-1 h-3 w-3" />
                Revisar
              </Link>
            </Button>
          ) : task.itemType === "auto" ? (
            <Button asChild variant="outline" size="sm" className="h-7 text-xs">
              <Link to={task.actionUrl ?? "/"}>
                <ArrowRight className="mr-1 h-3 w-3" />
                Abrir
              </Link>
            </Button>
          ) : null}
          {isPersisted && (
            <div className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
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
// Sidebar (right column): new manual task, batch actions, kind summary
// ---------------------------------------------------------------------------
export function NewManualTaskCard({
  title,
  setTitle,
  priority,
  setPriority,
  onSubmit,
  isPending,
}: {
  title: string
  setTitle: (v: string) => void
  priority: string
  setPriority: (v: string) => void
  onSubmit: (e: FormEvent) => void
  isPending: boolean
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-[14px]">Nueva tarea manual</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <form className="grid gap-2" onSubmit={onSubmit}>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Describe la tarea..."
            className="h-9"
          />
          <div className="flex gap-2">
            <select
              className="h-9 flex-1 rounded-md border bg-background px-3 text-sm"
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            >
              <option value="normal">Normal</option>
              <option value="high">Alta</option>
              <option value="critical">Crítica</option>
              <option value="low">Baja</option>
            </select>
            <Button size="sm" disabled={isPending || !title.trim()} className="gap-1">
              <Plus className="h-3.5 w-3.5" />
              Crear
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

export function BatchActionsCard({
  onAction,
  isPending,
  result,
  error,
}: {
  onAction: (action: string) => void
  isPending: boolean
  result: { matched: number; updated: number; enqueued: number } | undefined
  error: Error | null
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-[14px]">Acciones en lote</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start"
          onClick={() => onAction("retry_failed_jobs")}
          disabled={isPending}
        >
          <RotateCcw className="mr-2 h-3.5 w-3.5" />
          Reintentar jobs fallidos
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start"
          onClick={() => onAction("approve_high_confidence_ocr")}
          disabled={isPending}
        >
          <CheckCircle2 className="mr-2 h-3.5 w-3.5" />
          Aprobar OCR fiable
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="w-full justify-start"
          onClick={() => onAction("reprocess_low_quality")}
          disabled={isPending}
        >
          <FileWarning className="mr-2 h-3.5 w-3.5" />
          Reprocesar baja calidad
        </Button>
        {result && (
          <p className="rounded-md border bg-slate-50 p-2 text-xs text-muted-foreground">
            Encontrados: {result.matched}. Actualizados: {result.updated}. Encolados:{" "}
            {result.enqueued}.
          </p>
        )}
        {error && <p className="text-xs text-destructive">{error.message}</p>}
      </CardContent>
    </Card>
  )
}

export function KindSummaryCard({
  kindCounts,
  activeKind,
  onPick,
}: {
  kindCounts: Record<string, number>
  activeKind: string
  onPick: (kind: string) => void
}) {
  const entries = Object.entries(kindCounts)
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-[14px]">Resumen por tipo</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {entries.map(([kind, count]) => {
          const cfg = getKindConfig(kind)
          const KindIcon = ICON_MAP[cfg.icon] ?? FileSearch
          return (
            <button
              key={kind}
              type="button"
              className={cn(
                "flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-colors hover:bg-slate-50",
                activeKind === kind && "border-[var(--primary)] bg-[var(--primary-light)]",
              )}
              onClick={() => onPick(kind)}
            >
              <span className="flex items-center gap-2">
                <KindIcon className="h-3.5 w-3.5 text-[var(--text-muted)]" />
                <span>{cfg.label}</span>
              </span>
              <Badge variant="outline">{count}</Badge>
            </button>
          )
        })}
        {!entries.length && (
          <p className="text-sm text-muted-foreground">Sin incidencias abiertas.</p>
        )}
      </CardContent>
    </Card>
  )
}

// Empty-state helper for the main list.
export function EmptyInboxState() {
  return (
    <Card>
      <CardContent className="py-8">
        <EmptyState
          title="Sin tareas pendientes"
          description="No hay incidencias abiertas que requieran atención. ¡Buen trabajo!"
          icon={<CheckCircle2 className="h-8 w-8 text-[var(--emerald)]" />}
        />
      </CardContent>
    </Card>
  )
}

// Re-export the useState from a top-level import path to avoid the page
// having to remember to import it from react.
export { useState }
