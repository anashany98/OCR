import { useState } from "react"

import { useAdminLearningData } from "./useAdminLearningData"
import {
  HistoryCard,
  ImpactSimulatorPlaceholder,
  LearningSummaryCard,
  PatternsCard,
  SuggestionDetailCard,
  SuggestionListCard,
} from "./learning-sections"
import type { LearningViewProps } from "./learning-types"

function LearningView({
  suggestions,
  patterns,
  counts,
  approveSuggestion,
  rejectSuggestion,
  enablePattern,
  disablePattern,
}: LearningViewProps) {
  const [filter, setFilter] = useState<"pending" | "approved" | "all">("pending")
  const [selectedSuggestion, setSelectedSuggestion] = useState<LearningViewProps["suggestions"][number] | null>(null)

  const filtered = (() => {
    if (filter === "pending") return suggestions.filter((s) => s.status === "pending")
    if (filter === "approved") return suggestions.filter((s) => s.status === "approved" || s.status === "applied")
    return suggestions
  })()

  const historyItems = suggestions.filter((s) => s.status !== "pending")
  const activePatterns = patterns.filter((p) => p.status === "active")
  const pendingCount = counts?.pending ?? suggestions.filter((s) => s.status === "pending").length

  return (
    <div className="space-y-6">
      <LearningSummaryCard counts={counts} pendingCount={pendingCount} activePatternCount={activePatterns.length} />

      {selectedSuggestion && (
        <SuggestionDetailCard
          suggestion={selectedSuggestion}
          onClose={() => setSelectedSuggestion(null)}
          onApprove={() => { approveSuggestion.mutate(selectedSuggestion.id); setSelectedSuggestion(null) }}
          onReject={() => { rejectSuggestion.mutate(selectedSuggestion.id); setSelectedSuggestion(null) }}
          isApproving={approveSuggestion.isPending}
          isRejecting={rejectSuggestion.isPending}
        />
      )}

      <SuggestionListCard
        filtered={filtered}
        filter={filter}
        setFilter={setFilter}
        approveSuggestion={approveSuggestion}
        rejectSuggestion={rejectSuggestion}
        onSelect={setSelectedSuggestion}
      />

      <HistoryCard historyItems={historyItems} />
      <PatternsCard patterns={patterns} enablePattern={enablePattern} disablePattern={disablePattern} />
      <ImpactSimulatorPlaceholder />
    </div>
  )
}

export function AdminLearningPage() {
  const { queries, mutations } = useAdminLearningData()

  return (
    <LearningView
      suggestions={queries.learningSuggestions.data ?? []}
      patterns={queries.learnedPatterns.data ?? []}
      counts={queries.learningCounts.data}
      approveSuggestion={{ mutate: (id: number) => mutations.approveSuggestion.mutate(id), isPending: mutations.approveSuggestion.isPending, data: mutations.approveSuggestion.data, isError: mutations.approveSuggestion.isError, error: mutations.approveSuggestion.error }}
      rejectSuggestion={{ mutate: (id: number) => mutations.rejectSuggestion.mutate(id), isPending: mutations.rejectSuggestion.isPending, data: mutations.rejectSuggestion.data, isError: mutations.rejectSuggestion.isError, error: mutations.rejectSuggestion.error }}
      enablePattern={{ mutate: (id: number) => mutations.enablePattern.mutate(id), isPending: mutations.enablePattern.isPending, data: mutations.enablePattern.data, isError: mutations.enablePattern.isError, error: mutations.enablePattern.error }}
      disablePattern={{ mutate: (id: number) => mutations.disablePattern.mutate(id), isPending: mutations.disablePattern.isPending, data: mutations.disablePattern.data, isError: mutations.disablePattern.isError, error: mutations.disablePattern.error }}
    />
  )
}
