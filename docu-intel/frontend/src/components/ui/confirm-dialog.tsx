import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type ConfirmDialogProps = {
  open: boolean
  title: string
  description?: string
  confirmLabel: string
  cancelLabel?: string
  tone?: "default" | "danger"
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancelar",
  tone = "default",
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  if (!open) return null
  const titleId = "confirm-dialog-title"
  const descriptionId = description ? "confirm-dialog-description" : undefined

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className="w-full max-w-sm rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-4 shadow-xl"
      >
        <h2 id={titleId} className="text-base font-semibold text-[var(--text-primary)]">
          {title}
        </h2>
        {description ? (
          <p id={descriptionId} className="mt-2 text-sm text-[var(--text-secondary)]">
            {description}
          </p>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className={cn(tone === "danger" && "bg-[var(--danger)] hover:bg-[var(--danger)]/90")}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
