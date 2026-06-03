import type { ClassificationSuggestion, LearnedPattern } from "@/types/api"
import { buildSearchParams, request } from "./core"

export interface LearningHealthSnapshot {
  suggestion_counts: Record<string, number>
  oldest_pending_age_seconds: number | null
  stale_pending_count: number
  top_clients_by_pending: { client_id: number | null; pending: number }[]
  circuit_breaker: { max_per_client: number; window_seconds: number }
  learned_patterns: {
    counts: Record<string, number>
    top_active: {
      id: number
      pattern_value: string
      target_class: string | null
      applied_count: number
    }[]
  }
  stale_policy: { threshold_days: number }
}

export const learningApi = {
  classificationSuggestions: (params?: { status?: string; suggestion_type?: string; document_id?: number; limit?: number }) =>
    request<ClassificationSuggestion[]>("/admin/classification-suggestions" + buildSearchParams(params)),
  classificationSuggestionCounts: () =>
    request<Record<string, number>>("/admin/classification-suggestions/counts"),
  approveSuggestion: (id: number) =>
    request<ClassificationSuggestion>(`/admin/classification-suggestions/${id}/approve`, { method: "POST" }),
  rejectSuggestion: (id: number) =>
    request<ClassificationSuggestion>(`/admin/classification-suggestions/${id}/reject`, { method: "POST" }),
  learnedPatterns: (params?: { status?: string; limit?: number }) =>
    request<LearnedPattern[]>("/admin/learned-patterns" + buildSearchParams(params)),
  disablePattern: (id: number) =>
    request<LearnedPattern>(`/admin/learned-patterns/${id}/disable`, { method: "POST" }),
  enablePattern: (id: number) =>
    request<LearnedPattern>(`/admin/learned-patterns/${id}/enable`, { method: "POST" }),
  health: () => request<LearningHealthSnapshot>("/admin/learning/health"),
  triggerAutoRejectStale: () =>
    request<{ marked_stale: number; rejected: number; remaining: number }>(
      "/admin/learning/auto-reject-stale",
      { method: "POST" },
    ),
}
