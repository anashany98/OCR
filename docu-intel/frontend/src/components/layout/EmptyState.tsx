import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function EmptyState({
  title,
  description,
  action,
  onAction,
  icon,
  className,
}: {
  title: string
  description: string
  action?: string
  onAction?: () => void
  icon?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex min-h-[280px] flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-[var(--border-2)] bg-[var(--bg-surface)]/60 p-8 text-center",
        className,
      )}
    >
      {icon && (
        <div className="flex h-24 w-32 items-center justify-center text-[var(--accent)] opacity-90">{icon}</div>
      )}
      <div className="space-y-1.5">
        <h3 className="font-display text-[18px] font-medium leading-tight tracking-tight text-[var(--text-primary)]">
          {title}
        </h3>
        <p className="mx-auto max-w-md text-[13px] text-[var(--text-muted)] leading-relaxed">{description}</p>
      </div>
      {action ? (
        <Button className="mt-2" type="button" variant="outline" size="sm" onClick={onAction}>
          {action}
        </Button>
      ) : null}
    </div>
  )
}
