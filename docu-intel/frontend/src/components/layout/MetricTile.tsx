import type { ReactNode } from "react"

import { cn } from "@/lib/utils"
import type { StatusTone } from "@/lib/status"

const toneConfig: Record<StatusTone, { bg: string; border: string; dot: string; label: string; value: string; meta: string; icon?: string }> = {
  success: {
    bg: "bg-[var(--emerald-light)]",
    border: "border-[#A7F3D0]",
    dot: "bg-[var(--emerald)]",
    label: "text-[#065F46]",
    value: "text-[#065F46]",
    meta: "text-[#047857]",
  },
  warning: {
    bg: "bg-[var(--amber-light)]",
    border: "border-[#FDE68A]",
    dot: "bg-[var(--amber)]",
    label: "text-[#92400E]",
    value: "text-[#92400E]",
    meta: "text-[#B45309]",
  },
  danger: {
    bg: "bg-[var(--rose-light)]",
    border: "border-[#FECDD3]",
    dot: "bg-[var(--rose)]",
    label: "text-[#9F1239]",
    value: "text-[#9F1239]",
    meta: "text-[#BE123C]",
  },
  info: {
    bg: "bg-[var(--sky-light)]",
    border: "border-[#BAE6FD]",
    dot: "bg-[var(--sky)]",
    label: "text-[#075985]",
    value: "text-[#075985]",
    meta: "text-[#0369A1]",
  },
  neutral: {
    bg: "bg-white",
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
        "group relative overflow-hidden rounded-xl border p-5 transition-all duration-150 hover:-translate-y-0.5 hover:shadow-md",
        cfg.bg,
        cfg.border,
        className
      )}
    >
      {/* Decorative corner dot */}
      <span className={cn("status-dot absolute right-4 top-4 opacity-40", cfg.dot)} />

      <div className="flex items-start justify-between gap-4">
        <p className={cn("text-[11px] font-semibold uppercase tracking-widest", cfg.label)}>{title}</p>
        {icon && <div className={cn("opacity-60 transition-opacity group-hover:opacity-100", cfg.label)}>{icon}</div>}
      </div>

      <div className={cn("mt-3 text-3xl font-semibold tracking-tight", cfg.value)}>{value}</div>

      {meta && (
        <p className={cn("mt-1.5 text-[12px] font-medium", cfg.meta)}>{meta}</p>
      )}
    </div>
  )
}