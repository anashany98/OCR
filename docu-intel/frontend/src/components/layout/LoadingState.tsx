import { Skeleton } from "@/components/ui/skeleton"

export function LoadingState({ label = "Cargando datos..." }: { label?: string }) {
  return (
    <div className="grid gap-3" role="status" aria-busy="true" aria-label={label}>
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-24 w-full" />
      <p className="text-xs text-[var(--text-muted)]">{label}</p>
    </div>
  )
}
