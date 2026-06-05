import { toast as sonnerToast } from "sonner"

/**
 * Centralized toast helpers. We wrap Sonner so we can:
 * - Standardize titles and descriptions per tone
 * - Swap the underlying library without touching call sites
 * - Add error parsing (ApiError → message) in one place
 *
 * Usage:
 *   import { notify } from "@/lib/toast"
 *   notify.success("Documento subido")
 *   notify.error(apiError)          // accepts Error or ApiError
 *   notify.promise(uploadMutation, { loading: "...", success: "...", error: "..." })
 */
import { ApiError } from "@/api/core"

function extractMessage(error: unknown, fallback = "Algo salió mal"): string {
  if (error instanceof ApiError) return error.message || fallback
  if (error instanceof Error) return error.message || fallback
  if (typeof error === "string") return error
  return fallback
}

export const notify = {
  success(message: string, description?: string) {
    sonnerToast.success(message, { description })
  },
  info(message: string, description?: string) {
    sonnerToast.info(message, { description })
  },
  warning(message: string, description?: string) {
    sonnerToast.warning(message, { description })
  },
  error(error: unknown, fallback?: string) {
    sonnerToast.error(extractMessage(error, fallback))
  },
  /**
   * Wrap a TanStack Query mutation. Shows loading → success/error toasts.
   * Pass `silent: true` to skip the loading toast (useful for quick ops).
   */
  promise<T>(
    promise: Promise<T>,
    messages: { loading: string; success: string; error?: string | ((err: unknown) => string) },
  ): Promise<T> {
    sonnerToast.promise(promise, {
      loading: messages.loading,
      success: messages.success,
      error: (err) => {
        if (typeof messages.error === "function") return messages.error(err)
        if (typeof messages.error === "string") return messages.error
        return extractMessage(err)
      },
    })
    return promise
  },
  dismiss(id?: string | number) {
    sonnerToast.dismiss(id)
  },
}
