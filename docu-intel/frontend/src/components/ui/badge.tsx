import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium tracking-wide transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-[var(--accent)] text-white",
        secondary: "border-transparent bg-[var(--bg-surface-2)] text-[var(--text-secondary)]",
        destructive: "border-transparent bg-[var(--danger)] text-white",
        outline: "border-[var(--border-2)] bg-transparent text-[var(--text-secondary)]",
        success:
          "border-[var(--positive)]/25 bg-[var(--positive-light)] text-[var(--text-on-success)]",
        info: "border-[var(--info)]/25 bg-[var(--info-light)] text-[var(--text-on-info)]",
        warning:
          "border-[var(--warning)]/25 bg-[var(--warning-light)] text-[var(--text-on-warning)]",
        danger: "border-[var(--danger)]/25 bg-[var(--danger-light)] text-[var(--text-on-danger)]",
        neutral: "border-[var(--border-2)] bg-[var(--bg-surface-2)] text-[var(--text-secondary)]",
      },
    },
    defaultVariants: {
      variant: "secondary",
    },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }
