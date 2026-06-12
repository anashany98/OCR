import { AdminLearningTab } from "./AdminLearningTab"
import { useAdminLearningData } from "./useAdminLearningData"

/**
 * F4b - Learning admin sub-route. Lazy-loaded via the router.
 */
export function AdminLearningRoute() {
  const { queries, mutations } = useAdminLearningData()

  return (
    <AdminLearningTab
      suggestions={queries.learningSuggestions.data ?? []}
      patterns={queries.learnedPatterns.data ?? []}
      counts={queries.learningCounts.data}
      approveSuggestion={{
        mutate: (id: number) => mutations.approveSuggestion.mutate(id),
        isPending: mutations.approveSuggestion.isPending,
        data: mutations.approveSuggestion.data,
        isError: mutations.approveSuggestion.isError,
        error: mutations.approveSuggestion.error,
      }}
      rejectSuggestion={{
        mutate: (id: number) => mutations.rejectSuggestion.mutate(id),
        isPending: mutations.rejectSuggestion.isPending,
        data: mutations.rejectSuggestion.data,
        isError: mutations.rejectSuggestion.isError,
        error: mutations.rejectSuggestion.error,
      }}
      enablePattern={{
        mutate: (id: number) => mutations.enablePattern.mutate(id),
        isPending: mutations.enablePattern.isPending,
        data: mutations.enablePattern.data,
        isError: mutations.enablePattern.isError,
        error: mutations.enablePattern.error,
      }}
      disablePattern={{
        mutate: (id: number) => mutations.disablePattern.mutate(id),
        isPending: mutations.disablePattern.isPending,
        data: mutations.disablePattern.data,
        isError: mutations.disablePattern.isError,
        error: mutations.disablePattern.error,
      }}
    />
  )
}
