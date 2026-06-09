/**
 * Compose the prompt that is sent to the LLM by prepending the
 * active filter context to the user's question.
 *
 * Kept as a pure function (no React, no API client) so it can be
 * unit-tested without a renderer. The current implementation is
 * intentionally simple: filters are appended as a single line
 * inside a "Filtros activos" header. The model is told to bias
 * its search to the requested supplier / document type when
 * present.
 */
export function composeQuestion(
  question: string,
  filters: { supplier: string; documentType: string },
): string {
  const active: string[] = []
  if (filters.supplier.trim()) {
    active.push(`proveedor: ${filters.supplier.trim()}`)
  }
  if (filters.documentType.trim()) {
    active.push(`tipo documental: ${filters.documentType.trim()}`)
  }
  if (!active.length) {
    return question
  }
  return `${question}\n\nFiltros activos: ${active.join(", ")}`
}
