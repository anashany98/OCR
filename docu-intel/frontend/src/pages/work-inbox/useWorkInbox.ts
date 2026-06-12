import { useCallback, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"
import { workInboxTarget } from "@/lib/operations"
import { notify } from "@/lib/toast"
import type { WorkInboxItem, WorkItem } from "@/types/api"

// ---------------------------------------------------------------------------
// F8b-cont3 - work-inbox hook
// ---------------------------------------------------------------------------
// Owns the queries for the inbox + persisted tasks, the local UI
// state (filters, expanded groups, comment drafts, new-task
// draft), the four mutations (batch action, create task, update
// task, add comment) and the pure helpers that merge the two
// streams into a single ``TaskItem`` shape the UI can render.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Task kind registry
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

const taskKindConfig: Record<string, { label: string; icon: string; tone: string }> = {
  ocr_failed: { label: "OCR fallido", icon: "ShieldAlert", tone: "danger" },
  low_ocr: { label: "OCR de baja confianza", icon: "FileWarning", tone: "warning" },
  unknown_type: { label: "Clasificación dudosa", icon: "FileSearch", tone: "warning" },
  duplicate: { label: "Duplicado detectado", icon: "FileSearch", tone: "info" },
  quarantine: { label: "Documento en cuarentena", icon: "ShieldAlert", tone: "danger" },
  accepted_budget_without_order: {
    label: "Presupuesto aceptado sin pedido",
    icon: "AlertTriangle",
    tone: "warning",
  },
  order_without_budget: {
    label: "Pedido sin presupuesto",
    icon: "AlertTriangle",
    tone: "warning",
  },
  amount_mismatch: { label: "Importes no coincidentes", icon: "AlertTriangle", tone: "danger" },
  missing_fields: {
    label: "Documento sin entidades clave",
    icon: "FileWarning",
    tone: "warning",
  },
  needs_human_review: { label: "Pendiente de validación", icon: "Eye", tone: "info" },
  failed_job: { label: "Job fallido", icon: "XCircle", tone: "danger" },
  processed_low_quality: { label: "Baja calidad documental", icon: "FileWarning", tone: "warning" },
  plan_without_scale: { label: "Plano sin escala", icon: "FileWarning", tone: "warning" },
}

export function getKindConfig(kind: string): { label: string; icon: string; tone: string } {
  return (
    taskKindConfig[kind] ?? { label: kind.replace(/_/g, " "), icon: "FileSearch", tone: "neutral" }
  )
}

export const PRIORITY_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  normal: 2,
  low: 3,
}

export const PRIORITY_LABELS: Record<string, string> = {
  critical: "Críticas",
  high: "Altas",
  normal: "Normales",
  low: "Bajas",
}

// ---------------------------------------------------------------------------
// Unified task shape
// ---------------------------------------------------------------------------
export type TaskItem = {
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
    priority:
      item.severity === "error" || item.severity === "critical"
        ? "critical"
        : item.severity === "warning"
          ? "high"
          : "normal",
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
    actionUrl: workInboxTarget({
      kind: item.kind,
      severity: item.priority,
      title: "",
      description: "",
      document_id: item.document_id,
      page_id: item.page_id,
      job_id: item.job_id,
      action_url: null,
      status: item.status,
      created_at: item.created_at,
    }),
    raw: item,
  }
}

// ---------------------------------------------------------------------------
// Pure helpers (testable)
// ---------------------------------------------------------------------------
export function groupByPriority(tasks: TaskItem[]): Record<string, TaskItem[]> {
  const groups: Record<string, TaskItem[]> = { critical: [], high: [], normal: [], low: [] }
  for (const task of tasks) {
    const p = task.priority in groups ? task.priority : "normal"
    groups[p].push(task)
  }
  return groups
}

export function countByKind(tasks: TaskItem[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const task of tasks) {
    counts[task.kind] = (counts[task.kind] ?? 0) + 1
  }
  return counts
}

export function filterTasks(
  tasks: TaskItem[],
  opts: { kind?: string; priority?: string; search?: string },
): TaskItem[] {
  const { kind, priority, search } = opts
  if (!kind && !priority && !search?.trim()) return tasks
  const q = search?.trim().toLowerCase() ?? ""
  return tasks.filter((task) => {
    if (kind && task.kind !== kind) return false
    if (priority && task.priority !== priority) return false
    if (q && !task.title.toLowerCase().includes(q) && !task.description.toLowerCase().includes(q)) {
      return false
    }
    return true
  })
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------
export function useWorkInbox() {
  const queryClient = useQueryClient()

  // UI state
  const [kindFilter, setKindFilter] = useState<string>("")
  const [priorityFilter, setPriorityFilter] = useState<string>("")
  const [searchTerm, setSearchTerm] = useState("")
  const [newTaskTitle, setNewTaskTitle] = useState("")
  const [newTaskPriority, setNewTaskPriority] = useState("normal")
  const [commentText, setCommentText] = useState<Record<number, string>>({})
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    new Set(["critical", "high", "normal", "low"]),
  )

  // Queries
  const inbox = useQuery({
    queryKey: ["work-inbox"],
    queryFn: () => api.workInbox({ limit: 200 }),
    refetchInterval: 10_000,
  })
  const persisted = useQuery({
    queryKey: ["work-items"],
    queryFn: () => api.workItems({ limit: 100 }),
    refetchInterval: 15_000,
  })

  // Mutations
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
      api.updateWorkItem(id, {
        status,
        resolution_notes: status === "resolved" ? "Resuelta desde centro de trabajo" : null,
      }),
    onSuccess: (_, vars) => {
      queryClient.invalidateQueries({ queryKey: ["work-items"] })
      const label =
        vars.status === "resolved"
          ? "resuelta"
          : vars.status === "ignored"
            ? "ignorada"
            : "actualizada"
      notify.success(`Tarea ${label}`)
    },
    onError: (err) => notify.error(err, "No se pudo actualizar la tarea"),
  })
  const addComment = useMutation({
    mutationFn: ({ id, body }: { id: number; body: string }) =>
      api.addWorkItemComment(id, { body }),
    onSuccess: (_, variables) => {
      setCommentText((current) => ({ ...current, [variables.id]: "" }))
      queryClient.invalidateQueries({ queryKey: ["work-items"] })
    },
    onError: (err) => notify.error(err, "No se pudo añadir el comentario"),
  })

  // Derived
  const autoTasks: TaskItem[] = (inbox.data ?? []).map(inboxToTask)
  const persistedTasks: TaskItem[] = (persisted.data ?? [])
    .filter((w) => w.status !== "resolved")
    .map(persistedToTask)
  const allTasks = [...autoTasks, ...persistedTasks]

  const filteredTasks = filterTasks(allTasks, {
    kind: kindFilter,
    priority: priorityFilter,
    search: searchTerm,
  })
  const grouped = groupByPriority(filteredTasks)
  const priorityKeys = Object.keys(PRIORITY_ORDER).filter((key) => grouped[key]?.length > 0)
  const availableKinds = Array.from(new Set(allTasks.map((t) => t.kind))).sort()

  const counts = {
    critical: allTasks.filter((t) => t.priority === "critical").length,
    high: allTasks.filter((t) => t.priority === "high").length,
    open: autoTasks.filter((t) => t.status === "open").length,
    persisted: persistedTasks.length,
  }

  const toggleGroup = useCallback((priority: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(priority)) next.delete(priority)
      else next.add(priority)
      return next
    })
  }, [])

  const clearFilters = useCallback(() => {
    setKindFilter("")
    setPriorityFilter("")
    setSearchTerm("")
  }, [])

  return {
    // queries
    inbox,
    persisted,
    // state
    kindFilter,
    setKindFilter,
    priorityFilter,
    setPriorityFilter,
    searchTerm,
    setSearchTerm,
    newTaskTitle,
    setNewTaskTitle,
    newTaskPriority,
    setNewTaskPriority,
    commentText,
    setCommentText,
    expandedGroups,
    toggleGroup,
    // derived
    autoTasks,
    persistedTasks,
    allTasks,
    filteredTasks,
    grouped,
    priorityKeys,
    availableKinds,
    counts,
    // mutations
    action,
    createTask,
    updateTask,
    addComment,
    // actions
    clearFilters,
  }
}

export type WorkInbox = ReturnType<typeof useWorkInbox>
export type { TaskKind }
