import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, FileWarning, MessageSquare, Plus, RefreshCw, RotateCcw, UserRoundCheck } from "lucide-react"

import { api } from "@/api/client"
import { ActionPanel } from "@/components/layout/ActionPanel"
import { EmptyState } from "@/components/layout/EmptyState"
import { MetricTile } from "@/components/layout/MetricTile"
import { PageHeader } from "@/components/layout/PageHeader"
import { Badge, type BadgeProps } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { workInboxTarget } from "@/lib/operations"
import { severityTone } from "@/lib/status"
import type { WorkInboxItem, WorkItem } from "@/types/api"

const labels: Record<string, string> = {
  low_ocr: "OCR bajo",
  unknown_type: "Sin clasificar",
  duplicate: "Duplicado",
  failed_job: "Job fallido",
  missing_fields: "Campos faltantes",
  accepted_budget_without_order: "Presupuesto sin pedido",
  processed_low_quality: "Baja calidad",
  needs_human_review: "Revisión humana",
}

export function WorkInboxPage() {
  const queryClient = useQueryClient()
  const [newTaskTitle, setNewTaskTitle] = useState("")
  const [newTaskPriority, setNewTaskPriority] = useState("normal")
  const [commentText, setCommentText] = useState<Record<number, string>>({})
  const inbox = useQuery({ queryKey: ["work-inbox"], queryFn: () => api.workInbox({ limit: 200 }), refetchInterval: 10000 })
  const persisted = useQuery({ queryKey: ["work-items"], queryFn: () => api.workItems({ limit: 100 }), refetchInterval: 15000 })
  const action = useMutation({
    mutationFn: api.runWorkInboxAction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["work-inbox"] })
      queryClient.invalidateQueries({ queryKey: ["jobs"] })
      queryClient.invalidateQueries({ queryKey: ["ocr-review"] })
      queryClient.invalidateQueries({ queryKey: ["operations-overview"] })
    },
  })
  const createTask = useMutation({
    mutationFn: () =>
      api.createWorkItem({
        kind: "manual",
        title: newTaskTitle.trim(),
        description: "Tarea creada desde bandeja operativa.",
        priority: newTaskPriority,
      }),
    onSuccess: () => {
      setNewTaskTitle("")
      queryClient.invalidateQueries({ queryKey: ["work-items"] })
    },
  })
  const updateTask = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      api.updateWorkItem(id, { status, resolution_notes: status === "resolved" ? "Resuelta desde bandeja" : null }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["work-items"] }),
  })
  const addComment = useMutation({
    mutationFn: ({ id, body }: { id: number; body: string }) => api.addWorkItemComment(id, { body }),
    onSuccess: (_, variables) => {
      setCommentText((current) => ({ ...current, [variables.id]: "" }))
      queryClient.invalidateQueries({ queryKey: ["work-items"] })
    },
  })

  const items = inbox.data ?? []
  const persistedItems = persisted.data ?? []
  const counts = items.reduce<Record<string, number>>((acc, item) => {
    acc[item.kind] = (acc[item.kind] ?? 0) + 1
    return acc
  }, {})
  const errors = items.filter((item) => severityTone(item.severity) === "danger").length
  const warnings = items.filter((item) => severityTone(item.severity) === "warning").length

  return (
    <>
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
        <PageHeader title="Bandeja de trabajo" description="Cola operativa de incidencias con acciones, prioridad y destino claro." />
        <Button type="button" variant="outline" size="sm" onClick={() => inbox.refetch()} disabled={inbox.isFetching}>
          <RefreshCw data-icon="inline-start" />
          Actualizar
        </Button>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <MetricTile title="Abiertas" value={items.length + persistedItems.filter((item) => item.status !== "resolved").length} meta="Items operativos" tone={items.length || persistedItems.length ? "info" : "success"} />
        <MetricTile title="Críticas" value={errors} meta="Bloquean operación" tone={errors ? "danger" : "success"} />
        <MetricTile title="Advertencias" value={warnings} meta="Requieren revisión" tone={warnings ? "warning" : "neutral"} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
        <Card className="overflow-hidden">
          <CardHeader className="flex-row items-center justify-between gap-3 border-b bg-slate-50/80">
            <CardTitle>Trabajo pendiente</CardTitle>
            <Badge variant="neutral">Auto-generado por reglas</Badge>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Prioridad</TableHead>
                    <TableHead>Incidencia</TableHead>
                    <TableHead>Responsable</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead>Fecha</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item, index) => (
                    <TableRow key={`${item.kind}-${item.document_id ?? "d"}-${item.job_id ?? "j"}-${item.page_id ?? "p"}-${index}`}>
                      <TableCell>
                        <Badge variant={toneToBadge(severityTone(item.severity))}>{item.severity}</Badge>
                      </TableCell>
                      <TableCell>
                        <p className="font-medium">{item.title}</p>
                        <p className="max-w-[620px] truncate text-xs text-muted-foreground">{item.description}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{labels[item.kind] ?? item.kind}</p>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2 text-muted-foreground">
                          <UserRoundCheck className="h-4 w-4" />
                          Operación
                        </div>
                      </TableCell>
                      <TableCell>{item.status ?? "abierta"}</TableCell>
                      <TableCell>{item.created_at ? new Date(item.created_at).toLocaleString() : "-"}</TableCell>
                      <TableCell className="text-right">
                        <Button asChild variant="outline" size="sm">
                          <Link to={workInboxTarget(item)}>Abrir</Link>
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!items.length ? (
                    <TableRow>
                      <TableCell colSpan={6} className="p-6">
                        <EmptyState title="No hay trabajo pendiente" description="La operación no tiene incidencias abiertas con las reglas actuales." />
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Tareas persistentes</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <form
                className="grid gap-2"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (newTaskTitle.trim()) createTask.mutate()
                }}
              >
                <Input value={newTaskTitle} onChange={(event) => setNewTaskTitle(event.target.value)} placeholder="Nueva tarea operativa" />
                <div className="flex gap-2">
                  <select className="h-9 flex-1 rounded-md border bg-background px-3 text-sm" value={newTaskPriority} onChange={(event) => setNewTaskPriority(event.target.value)}>
                    <option value="normal">Normal</option>
                    <option value="high">Alta</option>
                    <option value="critical">Crítica</option>
                    <option value="low">Baja</option>
                  </select>
                  <Button size="sm" disabled={createTask.isPending || !newTaskTitle.trim()}>
                    <Plus data-icon="inline-start" />
                    Crear
                  </Button>
                </div>
              </form>

              <div className="space-y-2">
                {persistedItems.slice(0, 8).map((item) => (
                  <div key={item.id} className="rounded-md border p-3 text-sm">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="font-medium">{item.title}</p>
                        <p className="text-xs text-muted-foreground">{item.description || labels[item.kind] || item.kind}</p>
                      </div>
                      <Badge variant={workItemVariant(item)}>{item.priority}</Badge>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span>{item.status}</span>
                      <span>{item.comments.length} comentarios</span>
                    </div>
                    <div className="mt-2 flex gap-2">
                      <Input
                        className="h-8"
                        value={commentText[item.id] ?? ""}
                        onChange={(event) => setCommentText((current) => ({ ...current, [item.id]: event.target.value }))}
                        placeholder="Comentario"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        disabled={!commentText[item.id]?.trim() || addComment.isPending}
                        onClick={() => addComment.mutate({ id: item.id, body: commentText[item.id].trim() })}
                        title="Comentar"
                      >
                        <MessageSquare />
                      </Button>
                      <Button
                        type="button"
                        size="icon"
                        disabled={updateTask.isPending || item.status === "resolved"}
                        onClick={() => updateTask.mutate({ id: item.id, status: "resolved" })}
                        title="Resolver"
                      >
                        <CheckCircle2 />
                      </Button>
                    </div>
                  </div>
                ))}
                {!persistedItems.length ? <p className="text-sm text-muted-foreground">Sin tareas persistentes.</p> : null}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Resumen por tipo</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              {Object.entries(counts).map(([kind, count]) => (
                <div key={kind} className="flex items-center justify-between rounded-md border px-3 py-2">
                  <span>{labels[kind] ?? kind}</span>
                  <Badge variant="outline">{count}</Badge>
                </div>
              ))}
              {!Object.keys(counts).length ? <p className="text-muted-foreground">Sin incidencias abiertas.</p> : null}
            </CardContent>
          </Card>

          <ActionPanel title="Acciones en lote">
            <Button type="button" className="w-full justify-start" variant="outline" onClick={() => action.mutate({ action: "retry_failed_jobs", limit: 100 })} disabled={action.isPending}>
              <RotateCcw data-icon="inline-start" />
              Reintentar jobs fallidos
            </Button>
            <Button type="button" className="w-full justify-start" variant="outline" onClick={() => action.mutate({ action: "approve_high_confidence_ocr", min_confidence: 0.85, limit: 200 })} disabled={action.isPending}>
              <CheckCircle2 data-icon="inline-start" />
              Aprobar OCR fiable
            </Button>
            <Button type="button" className="w-full justify-start" variant="outline" onClick={() => action.mutate({ action: "reprocess_low_quality", limit: 100 })} disabled={action.isPending}>
              <FileWarning data-icon="inline-start" />
              Reprocesar baja calidad
            </Button>
            {action.data ? (
              <p className="rounded-md border bg-slate-50 p-2 text-sm text-muted-foreground">
                Encontrados: {action.data.matched}. Actualizados: {action.data.updated}. Encolados: {action.data.enqueued}.
              </p>
            ) : null}
            {action.isError ? <p className="text-sm text-destructive">{action.error.message}</p> : null}
          </ActionPanel>
        </div>
      </div>
    </>
  )
}

function toneToBadge(tone: ReturnType<typeof severityTone>): BadgeProps["variant"] {
  if (tone === "danger") return "danger"
  if (tone === "warning") return "warning"
  if (tone === "info") return "info"
  if (tone === "success") return "success"
  return "neutral"
}

function workItemVariant(item: WorkItem): BadgeProps["variant"] {
  if (item.priority === "critical") return "danger"
  if (item.priority === "high") return "warning"
  if (item.status === "resolved") return "success"
  return "neutral"
}
