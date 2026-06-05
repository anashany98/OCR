import type { ReactNode } from "react"

import { cn } from "@/lib/utils"
import type { StatusTone } from "@/lib/status"

const toneConfig: Record<
  StatusTone,
  { bg: string; border: string; dot: string; label: string; value: string; meta: string; icon?: string }
> = {
  success: {
    bg: "bg-[var(--positive-light)]",
    border: "border-[var(--positive)]/20",
    dot: "bg-[var(--positive)]",
    label: "text-[var(--text-on-success)]",
    value: "text-[var(--text-on-success)]",
    meta: "text-[var(--text-on-success)]/70",
  },
  warning: {
    bg: "bg-[var(--warning-light)]",
    border: "border-[var(--warning)]/20",
    dot: "bg-[var(--warning)]",
    label: "text-[var(--text-on-warning)]",
    value: "text-[var(--text-on-warning)]",
    meta: "text-[var(--text-on-warning)]/70",
  },
  danger: {
    bg: "bg-[var(--danger-light)]",
    border: "border-[var(--danger)]/20",
    dot: "bg-[var(--danger)]",
    label: "text-[var(--text-on-danger)]",
    value: "text-[var(--text-on-danger)]",
    meta: "text-[var(--text-on-danger)]/70",
  },
  info: {
    bg: "bg-[var(--info-light)]",
    border: "border-[var(--info)]/20",
    dot: "bg-[var(--info)]",
    label: "text-[var(--text-on-info)]",
    value: "text-[var(--text-on-info)]",
    meta: "text-[var(--text-on-info)]/70",
  },
  neutral: {
    bg: "bg-[var(--bg-surface)]",
    border: "border-[var(--border)]",
    dot: "bg-[var(--text-muted)]",
    label: "text-[var(--text-muted)]",
    value: "text-[var(--text-primary)]",
    meta: "text-[var(--text-secondary)]",
  },
}

export function MetricTile({
  title,
  value,
  meta,
  tone = "neutral",
  icon,
  className,
}: {
  title: string
  value: ReactNode
  meta?: ReactNode
  tone?: StatusTone
  icon?: ReactNode
  className?: string
}) {
  const cfg = toneConfig[tone]
  return (
    <div
      className={cn(
        "group relative overflow-hidden rounded-xl border p-5 transition-all duration-base ease-out hover-lift",
        cfg.bg,
        cfg.border,
        className,
      )}
    >
      {/* Decorative corner dot */}
      <span className={cn("status-dot absolute right-5 top-5 opacity-50", cfg.dot)} />

      <div className="flex items-start justify-between gap-4">
        <p className={cn("text-[10px] font-semibold uppercase tracking-[0.12em]", cfg.label)}>{title}</p>
        {icon && <div className={cn("opacity-70 transition-opacity group-hover:opacity-100", cfg.label)}>{icon}</div>}
      </div>

      <div className={cn("mt-3 font-display text-[32px] font-medium leading-none tracking-tight tabular-nums", cfg.value)}>
        {value}
      </div>

      {meta && <p className={cn("mt-2 text-[12px] font-medium", cfg.meta)}>{meta}</p>}
    </div>
  )
}
