export function LoadingState({ label = "Cargando datos..." }: { label?: string }) {
  return (
    <div className="grid gap-3">
      <div className="h-10 animate-pulse rounded-md bg-slate-100" />
      <div className="h-24 animate-pulse rounded-md bg-slate-100" />
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  )
}
