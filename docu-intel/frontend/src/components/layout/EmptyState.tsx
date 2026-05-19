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
    <div className="flex min-h-36 flex-col items-center justify-center rounded-md border border-dashed bg-slate-50 p-6 text-center">
      <div className="mb-3 flex size-10 items-center justify-center rounded-md border bg-white text-slate-500">
        {icon ?? <FileSearch className="h-5 w-5" />}
      </div>
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      <p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p>
      {action ? (
        <Button className="mt-4" type="button" variant="outline" size="sm" onClick={onAction}>
          {action}
        </Button>
      ) : null}
    </div>
  )
}
