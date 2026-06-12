import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function PageToolbar({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-md border bg-card p-2 shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  )
}
