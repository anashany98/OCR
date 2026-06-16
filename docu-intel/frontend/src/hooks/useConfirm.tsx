/**
 * F9: promise-based confirmation hook.
 *
 * Replaces ``window.confirm`` (which is not accessible, not
 * themeable, blocks the JS thread, and gives a different visual
 * experience on every browser / OS) with a thin wrapper around the
 * project's :component:`ConfirmDialog` component.
 *
 * Usage:
 *
 *   const confirm = useConfirm()
 *   ...
 *   <Button onClick={async () => {
 *     const ok = await confirm({
 *       title: "¿Pausar ingesta?",
 *       description: "Se detendrán los nuevos escaneos hasta que reanudes.",
 *       confirmLabel: "Pausar",
 *       tone: "danger",
 *     })
 *     if (ok) pauseQueues.mutate()
 *   }}>Pausar</Button>
 *
 * The component renders a single ``ConfirmDialog`` at the bottom
 * of the tree (call ``<ConfirmDialogHost/>`` once at the app root
 * — see :component:`ConfirmDialogHost`). The hook returns a
 * ``Promise<boolean>`` that resolves to ``true`` when the user
 * confirms and ``false`` when they cancel / dismiss the dialog.
 */
import type { ReactNode } from "react"
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react"

import { ConfirmDialog } from "@/components/ui/confirm-dialog"

type ConfirmOptions = {
  title: string
  description?: string
  confirmLabel: string
  cancelLabel?: string
  tone?: "default" | "danger"
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>

const ConfirmContext = createContext<ConfirmFn | null>(null)

/**
 * Access the global confirm function. Returns a no-op
 * (``Promise<true>``) if the host is not mounted so call sites do
 * not have to null-check.
 */
export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext)
  return useCallback<ConfirmFn>(
    (options) => {
      if (!ctx) {
        // Without the host the safest fallback is to refuse the
        // action so an operator does not accidentally trigger a
        // destructive operation by forgetting to mount the host.
        // The hook is meant to be paired with :component:`ConfirmDialogHost`
        // at the app root; if it is missing this is a wiring bug.
        // eslint-disable-next-line no-console
        console.warn("useConfirm called without <ConfirmDialogHost /> mounted")
        return Promise.resolve(false)
      }
      return ctx(options)
    },
    [ctx],
  )
}

type PendingRequest = {
  options: ConfirmOptions
  resolve: (value: boolean) => void
}

/**
 * Render once at the app root (next to ``<AppShell/>`` /
 * ``<Toaster/>``). The host owns the dialog state and resolves
 * every pending promise when the user clicks a button. Children
 * are rendered so the host doubles as the context provider for
 * the rest of the app — it can be dropped into the tree as a
 * self-contained wrapper.
 */
export function ConfirmDialogHost({ children }: { children?: ReactNode }) {
  const [pending, setPending] = useState<PendingRequest | null>(null)
  const requestRef = useRef<PendingRequest | null>(null)

  const request = useCallback<ConfirmFn>((options) => {
    return new Promise<boolean>((resolve) => {
      const next: PendingRequest = { options, resolve }
      requestRef.current = next
      setPending(next)
    })
  }, [])

  const handleCancel = useCallback(() => {
    if (!pending) return
    pending.resolve(false)
    requestRef.current = null
    setPending(null)
  }, [pending])

  const handleConfirm = useCallback(() => {
    if (!pending) return
    pending.resolve(true)
    requestRef.current = null
    setPending(null)
  }, [pending])

  const contextValue = useMemo(() => request, [request])

  return (
    <ConfirmContext.Provider value={contextValue}>
      {children}
      {pending ? (
        <ConfirmDialog
          open
          title={pending.options.title}
          description={pending.options.description}
          confirmLabel={pending.options.confirmLabel}
          cancelLabel={pending.options.cancelLabel}
          tone={pending.options.tone}
          onConfirm={handleConfirm}
          onCancel={handleCancel}
        />
      ) : null}
    </ConfirmContext.Provider>
  )
}
