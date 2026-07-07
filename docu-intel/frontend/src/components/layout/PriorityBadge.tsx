import { cn } from "@/lib/utils"

type PriorityLevel = "critical" | "high" | "normal" | "low"

const priorityConfig: Record<PriorityLevel, { color: string; textColor: string; icon: string }> = {
  critical: { color: "bg-[var(--danger-light)]", textColor: "text-[var(--text-on-danger)]", icon: "●" },
  high: { color: "bg-[var(--warning-light)]", textColor: "text-[var(--text-on-warning)]", icon: "▲" },
  normal: { color: "bg-[var(--info-light)]", textColor: "text-[var(--text-on-info)]", icon: "■" },
  low: { color: "bg-[var(--bg-surface-2)]", textColor: "text-[var(--text-muted)]", icon: "▼" },
}

function normalizePriority(value: string | null | undefined): PriorityLevel {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase()
  if (normalized === "critical" || normalized === "critica" || normalized === "urgent")
    return "critical"
  if (normalized === "high" || normalized === "alta" || normalized === "urgente") return "high"
  if (normalized === "normal" || normalized === "media") return "normal"
  if (normalized === "low" || normalized === "baja") return "low"
  return "normal"
}

const labelMap: Record<PriorityLevel, string> = {
  critical: "Crítica",
  high: "Alta",
  normal: "Normal",
  low: "Baja",
}

export function PriorityBadge({
  priority,
  showLabel = true,
  className,
}: {
  priority: string | null | undefined
  showLabel?: boolean
  className?: string
}) {
  const level = normalizePriority(priority)
  const config = priorityConfig[level]

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
        config.color,
        config.textColor,
        className,
      )}
    >
      <span className="text-[10px] leading-none">{config.icon}</span>
      {showLabel && <span>{labelMap[level]}</span>}
    </span>
  )
}
