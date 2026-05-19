import { cn } from "@/lib/utils"
import { statusTone } from "@/lib/status"
import type { StatusTone } from "@/lib/status"

const dotColors: Record<StatusTone, string> = {
  success: "bg-[var(--emerald)]",
  info: "bg-[var(--sky)]",
  warning: "bg-[var(--amber)]",
  danger: "bg-[var(--rose)]",
  neutral: "bg-[var(--text-muted)]",
}

const textColors: Record<StatusTone, string> = {
  success: "text-[#065F46]",
  info: "text-[#075985]",
  warning: "text-[#92400E]",
  danger: "text-[#9F1239]",
  neutral: "text-[var(--text-secondary)]",
}

export function StatusBadge({ status }: { status: string }) {
  const tone = statusTone(status)
  const display = formatStatus(status)
  return (
    <span className={cn("inline-flex items-center gap-1.5")}>
      <span className={cn("status-dot", dotColors[tone])} />
      <span className={cn("text-[11px] font-medium capitalize", textColors[tone])}>{display}</span>
    </span>
  )
}

function formatStatus(status: string): string {
  return status.replace(/_/g, " ")
}