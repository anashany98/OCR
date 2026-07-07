import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

/**
 * Standard page header. The `actions` slot is rendered on the right at md+ and
 * stacked below the title on small viewports.
 *
 * Variants:
 *  - default: surface card with border, prominent title
 *  - plain: no background, used when the header sits inside another container
 *  - minimal: title only, no description
 */
export function PageHeader({
  title,
  description,
  actions,
  className,
  variant = "default",
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
  className?: string
  variant?: "default" | "plain" | "minimal"
}) {
  if (variant === "plain") {
    return (
      <div
        className={cn("flex flex-col gap-3 md:flex-row md:items-end md:justify-between", className)}
      >
        <div className="min-w-0 space-y-1">
          <h1 className="font-display text-[26px] font-medium leading-[1.15] tracking-tight text-[var(--text-primary)] md:text-[30px]">
            {title}
          </h1>
          {description && (
            <div className="text-[13px] text-[var(--text-muted)] leading-relaxed">
              {description}
            </div>
          )}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    )
  }

  if (variant === "minimal") {
    return (
      <div className={cn("flex items-center justify-between gap-3", className)}>
        <h1 className="truncate font-display text-[22px] font-medium tracking-tight text-[var(--text-primary)]">
          {title}
        </h1>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    )
  }

  return (
    <div
      className={cn(
        "mb-6 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] px-6 py-5 shadow-sm md:px-8 md:py-6",
        className,
      )}
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div className="min-w-0 space-y-1">
          <h1 className="font-display text-[24px] font-medium leading-[1.15] tracking-tight text-[var(--text-primary)] md:text-[28px]">
            {title}
          </h1>
          {description && (
            <div className="text-[13px] text-[var(--text-muted)] leading-relaxed">
              {description}
            </div>
          )}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  )
}
