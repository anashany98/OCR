import { useState } from "react"
import { Plus } from "lucide-react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"

import { Button } from "@/components/ui/button"
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form"
import { Input } from "@/components/ui/input"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import {
  BatchActionsCard,
  EmptyInboxState,
  KindSummaryCard,
  PriorityGroup,
  WorkInboxBreadcrumbs,
  WorkInboxFiltersToolbar,
  WorkInboxSummaryCards,
  WorkInboxTopBar,
} from "./components"
import { useWorkInbox } from "./useWorkInbox"

const taskSchema = z.object({
  title: z.string().min(1, "Título requerido"),
  priority: z.enum(["normal", "high", "critical", "low"]),
})
type TaskForm = z.infer<typeof taskSchema>

export function WorkInboxPage() {
  const w = useWorkInbox()
  const [sheetOpen, setSheetOpen] = useState(false)

  const form = useForm<TaskForm>({
    resolver: zodResolver(taskSchema),
    defaultValues: { title: "", priority: "normal" },
  })

  function onSubmit(data: TaskForm) {
    w.setNewTaskTitle(data.title)
    w.setNewTaskPriority(data.priority)
    w.createTask.mutate()
    form.reset()
    setSheetOpen(false)
  }

  return (
    <>
      <WorkInboxBreadcrumbs />
      <WorkInboxTopBar inbox={w.inbox} />

      <WorkInboxSummaryCards counts={w.counts} expandedGroups={w.expandedGroups} toggleGroup={w.toggleGroup} />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        {/* Left: filters + task list */}
        <div className="space-y-3">
          <WorkInboxFiltersToolbar
            kindFilter={w.kindFilter} setKindFilter={w.setKindFilter}
            priorityFilter={w.priorityFilter} setPriorityFilter={w.setPriorityFilter}
            searchTerm={w.searchTerm} setSearchTerm={w.setSearchTerm}
            availableKinds={w.availableKinds} onClear={w.clearFilters}
          />
          {w.priorityKeys.length === 0 ? (
            <EmptyInboxState />
          ) : (
            w.priorityKeys.map((priority) => (
              <PriorityGroup
                key={priority}
                priority={priority}
                tasks={w.grouped[priority]}
                expanded={w.expandedGroups.has(priority)}
                onToggle={() => w.toggleGroup(priority)}
                onUpdateTask={(id, status) => w.updateTask.mutate({ id, status })}
                commentText={w.commentText}
                onCommentChange={(id, text) => w.setCommentText((prev) => ({ ...prev, [id]: text }))}
                onAddComment={(id, body) => w.addComment.mutate({ id, body })}
                isUpdating={w.updateTask.isPending}
                isCommenting={w.addComment.isPending}
              />
            ))
          )}
        </div>

        {/* Right: sidebar */}
        <div className="space-y-3">
          <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
            <SheetTrigger asChild>
              <Button className="w-full gap-1.5"><Plus className="h-4 w-4" /> Nueva tarea</Button>
            </SheetTrigger>
            <SheetContent side="right" className="w-[380px] sm:w-[420px]">
              <SheetHeader>
                <SheetTitle>Crear tarea manual</SheetTitle>
              </SheetHeader>
              <Form {...form}>
                <form className="mt-6 space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
                  <FormField control={form.control} name="title" render={({ field }) => (
                    <FormItem>
                      <FormLabel>Descripción</FormLabel>
                      <FormControl><Input {...field} placeholder="Describe la tarea..." /></FormControl>
                      <FormMessage />
                    </FormItem>
                  )} />
                  <FormField control={form.control} name="priority" render={({ field }) => (
                    <FormItem>
                      <FormLabel>Prioridad</FormLabel>
                      <FormControl>
                        <select className="flex h-9 w-full rounded-md border border-[var(--border-2)] bg-[var(--bg-surface)] px-3 text-[13px] text-[var(--text-primary)]" {...field}>
                          <option value="normal">Normal</option>
                          <option value="high">Alta</option>
                          <option value="critical">Crítica</option>
                          <option value="low">Baja</option>
                        </select>
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )} />
                  <Button type="submit" className="w-full" disabled={w.createTask.isPending}>
                    {w.createTask.isPending ? "Creando..." : "Crear tarea"}
                  </Button>
                </form>
              </Form>
            </SheetContent>
          </Sheet>

          <BatchActionsCard
            onAction={(action) => {
              if (action === "retry_failed_jobs") w.action.mutate({ action, limit: 100 })
              else if (action === "approve_high_confidence_ocr") w.action.mutate({ action, min_confidence: 0.85, limit: 200 })
              else if (action === "reprocess_low_quality") w.action.mutate({ action, limit: 100 })
            }}
            isPending={w.action.isPending}
            result={w.action.data}
            error={w.action.error as Error | null}
          />
          <KindSummaryCard
            kindCounts={(() => {
              const counts: Record<string, number> = {}
              for (const task of w.allTasks) counts[task.kind] = (counts[task.kind] ?? 0) + 1
              return counts
            })()}
            activeKind={w.kindFilter}
            onPick={(kind) => w.setKindFilter(w.kindFilter === kind ? "" : kind)}
          />
        </div>
      </div>
    </>
  )
}
