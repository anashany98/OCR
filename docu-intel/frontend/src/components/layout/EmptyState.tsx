import type { ReactNode } from "react"
import { FileSearch } from "lucide-react"

import { Button } from "@/components/ui/button"

export function EmptyState({
  title,
  description,
  action,
  onAction,
  icon,
}: {
  title: string
  description: string
  action?: string
  onAction?: () => void
  icon?: ReactNode
}) {
  return (
    <div className="flex min-h-36 flex-col items-center justify-center rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-surface-2)] p-6 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-md border border-[var(--border)] bg-white text-[var(--text-muted)]">
        {icon ?? <FileSearch className="h-5 w-5" />}
      </div>
      <h3 className="text-[14px] font-semibold text-[var(--text-primary)]">{title}</h3>
      <p className="mt-1 max-w-md text-[13px] text-[var(--text-muted)]">{description}</p>
      {action ? (
        <Button className="mt-4" type="button" variant="outline" size="sm" onClick={onAction}>
          {action}
        </Button>
      ) : null}
    </div>
  )
}