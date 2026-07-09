import React from "react"
import ReactDOM from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "react-router-dom"
import { Toaster } from "sonner"

import { ErrorBoundary } from "@/components/ErrorBoundary"
import { ConfirmDialogHost } from "@/hooks/useConfirm"
import { DensityProvider } from "@/hooks/useDensity"
import { AuthProvider } from "@/hooks/useAuth"
import { router } from "@/routes/router"
import { SentryErrorBoundary, initSentry } from "@/lib/sentry"
import "@/index.css"

// Initialize GlitchTip / Sentry as early as possible. Safe to call without a DSN.
initSentry()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
})

// Wrap the app in Sentry's ErrorBoundary when Sentry is active. We keep our own
// ErrorBoundary for the styled fallback UI; Sentry's runs first and reports
// the error before we render the fallback.
const RootErrorBoundary: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const sentryEnabled = Boolean(import.meta.env.VITE_SENTRY_DSN)
  if (sentryEnabled) {
    return (
      <SentryErrorBoundary fallback={<ErrorBoundary>{children}</ErrorBoundary>}>
        <ErrorBoundary>{children}</ErrorBoundary>
      </SentryErrorBoundary>
    )
  }
  return <ErrorBoundary>{children}</ErrorBoundary>
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <DensityProvider>
          <ConfirmDialogHost>
          <RootErrorBoundary>
            <RouterProvider router={router} />
            <Toaster
              position="bottom-right"
              richColors
              closeButton
              duration={5000}
              toastOptions={{
                classNames: {
                  toast: "font-sans",
                  title: "text-[13px] font-medium",
                  description: "text-[12px] text-[var(--text-muted)]",
                },
              }}
            />
          </RootErrorBoundary>
          </ConfirmDialogHost>
        </DensityProvider>
      </AuthProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
