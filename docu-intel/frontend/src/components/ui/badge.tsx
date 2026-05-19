import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-semibold transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-[var(--primary)] text-white",
        secondary: "border-transparent bg-[var(--bg-surface-2)] text-[var(--text-secondary)]",
        destructive: "border-transparent bg-[var(--rose)] text-white",
        outline: "border-[var(--border)] bg-transparent text-[var(--text-secondary)]",
        success: "border-[#A7F3D0] bg-[var(--emerald-light)] text-[#065F46]",
        info: "border-[#BAE6FD] bg-[var(--sky-light)] text-[#075985]",
        warning: "border-[#FDE68A] bg-[var(--amber-light)] text-[#92400E]",
        danger: "border-[#FECDD3] bg-[var(--rose-light)] text-[#9F1239]",
        neutral: "border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-secondary)]",
      },
    },
    defaultVariants: {
      variant: "secondary",
    },
  }
)

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}

export { Badge, badgeVariants }