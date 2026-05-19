import type { ReactNode } from "react"

import { cn } from "@/lib/utils"
import type { StatusTone } from "@/lib/status"

const toneClasses: Record<StatusTone, string> = {
  success: "border-emerald-200 bg-emerald-50/70 text-emerald-900",
  info: "border-sky-200 bg-sky-50/70 text-sky-900",
  warning: "border-amber-200 bg-amber-50/70 text-amber-900",
  danger: "border-rose-200 bg-rose-50/70 text-rose-900",
  neutral: "border-slate-200 bg-white text-slate-900",
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
  return (
    <div className={cn("rounded-md border p-4 shadow-sm", toneClasses[tone], className)}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium uppercase tracking-normal text-slate-500">{title}</p>
        {icon ? <div className="text-slate-500">{icon}</div> : null}
      </div>
      <div className="mt-3 text-2xl font-semibold tracking-normal">{value}</div>
      {meta ? <p className="mt-1 text-xs text-slate-500">{meta}</p> : null}
    </div>
  )
}
