export type StatusTone = "success" | "info" | "warning" | "danger" | "neutral"

const successStates = new Set([
  "processed",
  "processed_ok",
  "completed",
  "finished",
  "approved",
  "ready",
  "validado",
  "ok",
])
const infoStates = new Set(["processing", "running", "in_progress", "queued", "active", "uploaded"])
const warningStates = new Set([
  "pending",
  "needs_review",
  "needs_human_review",
  "processed_low_quality",
  "processed_missing_fields",
  "warning",
  "degraded",
])
const dangerStates = new Set(["failed", "error", "critical", "rejected", "quarantine", "blocked"])
const neutralStates = new Set(["duplicate", "archived", "cancelled", "skipped", "unknown"])

export function statusTone(status: string | null | undefined): StatusTone {
  const normalized = normalize(status)
  if (successStates.has(normalized)) return "success"
  if (infoStates.has(normalized)) return "info"
  if (warningStates.has(normalized)) return "warning"
  if (dangerStates.has(normalized)) return "danger"
  if (neutralStates.has(normalized)) return "neutral"
  return "neutral"
}

export function severityTone(severity: string | null | undefined): StatusTone {
  const normalized = normalize(severity)
  if (normalized === "critical" || normalized === "error") return "danger"
  if (normalized === "warning") return "warning"
  if (normalized === "info") return "info"
  return "neutral"
}

function normalize(value: string | null | undefined) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
}
