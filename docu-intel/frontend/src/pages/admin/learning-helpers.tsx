import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { statusLabels } from "./learning-types"

export function InfoItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-md border bg-[var(--bg-surface)] px-3 py-2">
      <p className="text-[10px] font-semibold uppercase text-[var(--text-muted)]">{label}</p>
      <div className="mt-0.5 text-sm">{value}</div>
    </div>
  )
}

export function CountBadge({
  label,
  value,
  variant,
}: {
  label: string
  value: number
  variant: "warning" | "success" | "danger" | "info" | "neutral"
}) {
  const colors = {
    warning: "border-[var(--warning-light)] bg-[var(--warning-light)]/30 text-[var(--text-on-warning)]",
    success: "border-[var(--success-light)] bg-[var(--success-light)]/30 text-[var(--text-on-success)]",
    danger: "border-[var(--danger-light)] bg-[var(--danger-light)]/30 text-[var(--text-on-danger)]",
    info: "border-[var(--info-light)] bg-[var(--info-light)]/30 text-[var(--text-on-info)]",
    neutral: "border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-primary)]",
  }
  return (
    <div className={cn("flex items-center gap-2 rounded-lg border px-4 py-2.5", colors[variant])}>
      <span className="text-2xl font-bold">{value}</span>
      <span className="text-xs font-medium">{label}</span>
    </div>
  )
}

export function LearningStatusBadge({ status }: { status: string }) {
  const variants: Record<string, "success" | "warning" | "danger" | "info" | "neutral"> = {
    pending: "warning",
    approved: "info",
    rejected: "danger",
    applied: "success",
    active: "success",
    disabled: "neutral",
  }
  return (
    <Badge variant={variants[status] ?? "neutral"} className="text-[10px]">
      {statusLabels[status] ?? status}
    </Badge>
  )
}
