export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-5 space-y-1">
      <h1 className="text-[20px] font-semibold text-[var(--text-primary)] tracking-tight">{title}</h1>
      {description && (
        <p className="text-[13px] text-[var(--text-muted)] leading-relaxed">{description}</p>
      )}
    </div>
  )
}