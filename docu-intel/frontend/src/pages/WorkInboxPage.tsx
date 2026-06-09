import {
  BatchActionsCard,
  EmptyInboxState,
  KindSummaryCard,
  NewManualTaskCard,
  PriorityGroup,
  WorkInboxBreadcrumbs,
  WorkInboxFiltersToolbar,
  WorkInboxSummaryCards,
  WorkInboxTopBar,
} from "./work-inbox/components"
import { useWorkInbox } from "./work-inbox/useWorkInbox"

// ---------------------------------------------------------------------------
// F8b-cont3 - work-inbox page composition
//
// The previous file was 31 KB / 807 lines mixing data fetching
// (inbox + persisted), four mutations, filters/search/expended
// groups state, task-kind registry, priority grouping logic and
// inline sub-components (SummaryCard, PriorityGroup, TaskRow,
// NewManualTaskCard, BatchActionsCard, KindSummaryCard).
//
// After F8b-cont3:
// - useWorkInbox() owns every piece of state and side effect.
// - The four pure helpers (getKindConfig, groupByPriority,
//   countByKind, filterTasks) are exported and unit-tested.
// - The components are split out into separate, testable pieces
//   (SummaryCard, PriorityGroup, TaskRow, FiltersToolbar, etc.).
// - The page itself is just a layout shell: top bar, summary
//   cards, two-column grid with task list (left) and sidebar
//   (right).
// ---------------------------------------------------------------------------
export function WorkInboxPage() {
  const w = useWorkInbox()

  return (
    <>
      <WorkInboxBreadcrumbs />
      <WorkInboxTopBar inbox={w.inbox} />

      <WorkInboxSummaryCards
        counts={w.counts}
        expandedGroups={w.expandedGroups}
        toggleGroup={w.toggleGroup}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        {/* Left: filters + task list */}
        <div className="space-y-4">
          <WorkInboxFiltersToolbar
            kindFilter={w.kindFilter}
            setKindFilter={w.setKindFilter}
            priorityFilter={w.priorityFilter}
            setPriorityFilter={w.setPriorityFilter}
            searchTerm={w.searchTerm}
            setSearchTerm={w.setSearchTerm}
            availableKinds={w.availableKinds}
            onClear={w.clearFilters}
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
                onCommentChange={(id, text) =>
                  w.setCommentText((prev) => ({ ...prev, [id]: text }))
                }
                onAddComment={(id, body) => w.addComment.mutate({ id, body })}
                isUpdating={w.updateTask.isPending}
                isCommenting={w.addComment.isPending}
              />
            ))
          )}
        </div>

        {/* Right: sidebar */}
        <div className="space-y-4">
          <NewManualTaskCard
            title={w.newTaskTitle}
            setTitle={w.setNewTaskTitle}
            priority={w.newTaskPriority}
            setPriority={w.setNewTaskPriority}
            onSubmit={(e) => {
              e.preventDefault()
              if (w.newTaskTitle.trim()) w.createTask.mutate()
            }}
            isPending={w.createTask.isPending}
          />
          <BatchActionsCard
            onAction={(action) => {
              if (action === "retry_failed_jobs") {
                w.action.mutate({ action, limit: 100 })
              } else if (action === "approve_high_confidence_ocr") {
                w.action.mutate({ action, min_confidence: 0.85, limit: 200 })
              } else if (action === "reprocess_low_quality") {
                w.action.mutate({ action, limit: 100 })
              }
            }}
            isPending={w.action.isPending}
            result={w.action.data}
            error={w.action.error as Error | null}
          />
          <KindSummaryCard
            kindCounts={(() => {
              const counts: Record<string, number> = {}
              for (const task of w.allTasks) {
                counts[task.kind] = (counts[task.kind] ?? 0) + 1
              }
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
