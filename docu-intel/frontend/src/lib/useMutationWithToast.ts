import { useMutation, type UseMutationOptions, type UseMutationResult } from "@tanstack/react-query"

import { notify } from "./toast"

type ToastMessages<TData, TError, TVariables> = {
  loading?: string
  success?: string | ((data: TData, variables: TVariables) => string)
  error?: string | ((err: TError) => string)
  silent?: boolean
}

type Options<TData, TError, TVariables, TContext> = Omit<
  UseMutationOptions<TData, TError, TVariables, TContext>,
  "mutationFn" | "onSuccess" | "onError"
> & {
  mutationFn: UseMutationOptions<TData, TError, TVariables, TContext>["mutationFn"]
  toast?: ToastMessages<TData, TError, TVariables>
  onSuccess?: (data: TData, variables: TVariables, context: TContext) => void
  onError?: (error: TError, variables: TVariables, context: TContext | undefined) => void
}

/**
 * Thin wrapper over useMutation that auto-emits Sonner toasts.
 *
 * Pass `toast: { loading, success, error, silent }` to enable. The `success`
 * callback receives the mutation data and can produce a contextual message
 * (e.g. "Documento #123 reprocesado"). If `silent: true`, only errors are
 * toasted (good for fast operations that already show inline feedback).
 */
export function useMutationWithToast<
  TData = unknown,
  TError = unknown,
  TVariables = void,
  TContext = unknown,
>(
  options: Options<TData, TError, TVariables, TContext>,
): UseMutationResult<TData, TError, TVariables, TContext> {
  const { toast, onSuccess, onError, ...rest } = options

  return useMutation<TData, TError, TVariables, TContext>({
    ...rest,
    onSuccess: (data, variables, context) => {
      if (toast && !toast.silent) {
        const message =
          typeof toast.success === "function" ? toast.success(data, variables) : toast.success
        if (message) notify.success(message)
      }
      onSuccess?.(data, variables, context)
    },
    onError: (error, variables, context) => {
      if (toast) {
        const message = typeof toast.error === "function" ? toast.error(error) : toast.error
        notify.error(error, message)
      }
      onError?.(error, variables, context)
    },
  })
}
