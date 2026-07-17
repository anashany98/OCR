import { cn } from "@/lib/utils"

type ConfidenceLevel = "high" | "medium" | "low" | "unknown"

const levelConfig: Record<ConfidenceLevel, { color: string; textColor: string; label: string }> = {
  high: {
    color: "bg-[var(--success-light)]",
    textColor: "text-[var(--text-on-success)]",
    label: "Alta",
  },
  medium: {
    color: "bg-[var(--warning-light)]",
    textColor: "text-[var(--text-on-warning)]",
    label: "Media",
  },
  low: {
    color: "bg-[var(--danger-light)]",
    textColor: "text-[var(--text-on-danger)]",
    label: "Baja",
  },
  unknown: { color: "bg-[var(--bg-surface-2)]", textColor: "text-[var(--text-muted)]", label: "—" },
}

function getConfidenceLevel(value: number | null | undefined): ConfidenceLevel {
  if (value == null) return "unknown"
  if (value >= 0.85) return "high"
  if (value >= 0.7) return "medium"
  return "low"
}

export function ConfidenceBadge({
  value,
  showLabel = true,
  className,
}: {
  value: number | null | undefined
  showLabel?: boolean
  className?: string
}) {
  const level = getConfidenceLevel(value)
  const config = levelConfig[level]

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        config.color,
        config.textColor,
        className,
      )}
    >
      <span
        className={cn("h-1.5 w-1.5 rounded-full", {
          "bg-[var(--success)]": level === "high",
          "bg-[var(--warning)]": level === "medium",
          "bg-[var(--danger)]": level === "low",
          "bg-[var(--text-muted)]": level === "unknown",
        })}
      />
      {showLabel && <span>{value != null ? `${Math.round(value * 100)}%` : config.label}</span>}
    </span>
  )
}
