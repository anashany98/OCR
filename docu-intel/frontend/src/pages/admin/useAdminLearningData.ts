/**
 * useAdminLearningData - queries and mutations for the
 * ``/admin/aprendizaje`` tab (classification suggestions, learned
 * patterns).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

export function useAdminLearningData() {
  const queryClient = useQueryClient()

  const learningSuggestions = useQuery({
    queryKey: ["learning-suggestions"],
    queryFn: () => api.classificationSuggestions({ limit: 100 }),
    refetchInterval: 15000,
  })
  const learningCounts = useQuery({
    queryKey: ["learning-counts"],
    queryFn: api.classificationSuggestionCounts,
    refetchInterval: 15000,
  })
  const learnedPatterns = useQuery({
    queryKey: ["learned-patterns"],
    queryFn: () => api.learnedPatterns({ limit: 100 }),
    refetchInterval: 15000,
  })

  const approveSuggestion = useMutation({
    mutationFn: (id: number) => api.approveSuggestion(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["learning-suggestions"] })
      void queryClient.invalidateQueries({ queryKey: ["learning-counts"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const rejectSuggestion = useMutation({
    mutationFn: (id: number) => api.rejectSuggestion(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["learning-suggestions"] })
      void queryClient.invalidateQueries({ queryKey: ["learning-counts"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const enablePattern = useMutation({
    mutationFn: (id: number) => api.enablePattern(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["learned-patterns"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const disablePattern = useMutation({
    mutationFn: (id: number) => api.disablePattern(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["learned-patterns"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })

  return {
    queries: { learningSuggestions, learningCounts, learnedPatterns },
    mutations: { approveSuggestion, rejectSuggestion, enablePattern, disablePattern },
  }
}

export type AdminLearningData = ReturnType<typeof useAdminLearningData>
