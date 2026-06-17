/**
 * Sanitise a filter value before it is interpolated into the LLM
 * prompt or used as a search filter.
 *
 * The filter is a free-text input on the chat UI; without
 * sanitisation an operator could paste newlines (which break the
 * "Filtros activos" header) or characters that confuse the model's
 * tool-call DSL. The allow-list keeps the surface narrow:
 * latin letters, digits, common Spanish punctuation, dot, comma,
 * underscore, hyphen and whitespace.
 */
export function sanitizeFilter(raw: string, maxLen = 40): string {
  if (!raw) return ""
  // 1) strip CR/LF so the value cannot break the "Filtros activos"
  //    header line or the JSON-encoded tool-call payload.
  // 2) collapse whitespace runs into a single space.
  // 3) drop every character outside the allow-list.
  // 4) cap to ``maxLen`` chars (default 40 — matches the legacy
  //    ``ALLOWED_REASONS`` length budget).
  return raw
    .replace(/[\r\n]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/[^A-Za-z0-9áéíóúüñÁÉÍÓÚÜÑ .,_-]/g, "")
    .trim()
    .slice(0, maxLen)
}

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
 *
 * Both filter values are passed through :func:`sanitizeFilter` so a
 * paste of newlines or non-latin characters cannot break the prompt
 * format or leak into a tool-call DSL.
 */
export function composeQuestion(
  question: string,
  filters: { supplier: string; documentType: string },
): string {
  const supplier = sanitizeFilter(filters.supplier)
  const documentType = sanitizeFilter(filters.documentType)
  const active: string[] = []
  if (supplier) {
    active.push(`proveedor: ${supplier}`)
  }
  if (documentType) {
    active.push(`tipo documental: ${documentType}`)
  }
  if (!active.length) {
    return question
  }
  return `${question}\n\nFiltros activos: ${active.join(", ")}`
}
