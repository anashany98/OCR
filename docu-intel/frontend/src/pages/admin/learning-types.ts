import type { ClassificationSuggestion, LearnedPattern } from "@/types/api"

export interface MutationLike<TData = unknown> {
  mutate: (vars: number) => void
  isPending: boolean
  data?: TData
  isError: boolean
  error: Error | null
}

export interface LearningViewProps {
  suggestions: ClassificationSuggestion[]
  patterns: LearnedPattern[]
  counts?: Record<string, number>
  approveSuggestion: MutationLike
  rejectSuggestion: MutationLike
  enablePattern: MutationLike
  disablePattern: MutationLike
}

export const suggestionLabels: Record<string, string> = {
  classification_correction: "Corrección de tipo",
  entity_link: "Vinculación de documentos",
  classification_rule: "Regla de clasificación",
  quality_feedback: "Feedback de calidad",
}

export const statusLabels: Record<string, string> = {
  pending: "Pendiente",
  approved: "Aprobada",
  rejected: "Rechazada",
  applied: "Aplicada",
  active: "Activo",
  disabled: "Desactivado",
}

export function riskLevel(confidence: number): { level: string; color: string; bg: string } {
  if (confidence >= 0.85)
    return { level: "Bajo", color: "text-[var(--text-on-success)]", bg: "bg-[var(--success-light)]" }
  if (confidence >= 0.7)
    return { level: "Medio", color: "text-[var(--text-on-warning)]", bg: "bg-[var(--warning-light)]" }
  return { level: "Alto", color: "text-[var(--text-on-danger)]", bg: "bg-[var(--danger-light)]" }
}

export function estimatedImpact(suggestion: ClassificationSuggestion): { docs: number; label: string } {
  if (suggestion.suggestion_type === "classification_rule") return { docs: 5, label: "~5 docs similares" }
  if (suggestion.suggestion_type === "classification_correction") return { docs: 1, label: "Solo este documento" }
  return { docs: 1, label: "Impacto directo" }
}
