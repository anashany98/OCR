export type DocumentViewId = "all" | "needs-review" | "failed" | "plans-without-scale" | "recent"

export type DocumentFilters = {
  q?: string
  status?: string
  document_type?: string
  quality_status?: string
  limit?: number
  offset?: number
}

export const documentViews: {
  id: DocumentViewId
  label: string
  description: string
  filters: DocumentFilters
}[] = [
  { id: "all", label: "Todos", description: "Últimos documentos registrados", filters: {} },
  {
    id: "needs-review",
    label: "OCR pendiente",
    description: "Documentos que requieren revisión humana",
    filters: { status: "needs_review" },
  },
  {
    id: "failed",
    label: "Fallidos",
    description: "Errores de ingesta o procesamiento",
    filters: { status: "failed" },
  },
  {
    id: "plans-without-scale",
    label: "Planos sin escala",
    description: "Planos que necesitan corrección de escala",
    filters: { document_type: "plano", quality_status: "needs_human_review" },
  },
  {
    id: "recent",
    label: "Últimos 7 días",
    description: "Entrada reciente para revisión rápida",
    filters: {},
  },
]

export function applyDocumentView(
  viewId: DocumentViewId,
  current: DocumentFilters = {},
): DocumentFilters {
  const view = documentViews.find((candidate) => candidate.id === viewId) ?? documentViews[0]
  return {
    q: current.q,
    ...view.filters,
    limit: current.limit ?? 25,
    offset: current.offset ?? 0,
  }
}
