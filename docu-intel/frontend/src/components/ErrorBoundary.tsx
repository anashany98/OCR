import { Component, type ReactNode } from "react"
import { AlertCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { captureException } from "@/lib/sentry"

interface ErrorBoundaryProps {
  children: ReactNode
  fallback?: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    // Always log to the console for local debugging.
    console.error("ErrorBoundary caught:", error, errorInfo)
    // Report to GlitchTip / Sentry when configured. captureException is a no-op
    // when Sentry is disabled, so it's safe to call unconditionally.
    captureException(error, { component_stack: errorInfo.componentStack ?? "" })
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback

      return (
        <div className="flex min-h-screen flex-col items-center justify-center p-8 text-center">
          <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-red-50 border border-red-200">
            <AlertCircle className="h-8 w-8 text-red-500" />
          </div>
          <h1 className="mb-2 text-xl font-bold text-[var(--text-primary)]">Algo salió mal</h1>
          <p className="mb-2 max-w-md text-sm text-[var(--text-muted)]">
            La aplicación encontró un error inesperado. Podés intentar recargar la página.
          </p>
          {this.state.error && (
            <details className="mb-4 max-w-md text-left">
              <summary className="cursor-pointer text-xs text-[var(--text-muted)]">
                Detalles del error
              </summary>
              <pre className="mt-2 rounded bg-[var(--bg-surface)] p-3 text-xs text-[var(--text-secondary)] whitespace-pre-wrap">
                {this.state.error.message}
              </pre>
            </details>
          )}
          <div className="flex gap-3">
            <Button type="button" variant="outline" size="sm" onClick={this.handleReset}>
              Reintentar
            </Button>
            <Button type="button" size="sm" onClick={() => window.location.reload()}>
              Recargar página
            </Button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
