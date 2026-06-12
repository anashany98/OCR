/**
 * GlitchTip (Sentry-compatible) client for the React app.
 *
 * GlitchTip exposes a Sentry-compatible API, so the official `@sentry/react`
 * SDK works as-is. This module is a thin wrapper that:
 *
 *   * reads the DSN from `VITE_SENTRY_DSN` (disabled when empty)
 *   * integrates with the React Router so navigation errors are captured
 *   * exposes a no-op `captureException` for callers that don't want to depend
 *     on the SDK directly
 *
 * The DSN format is Sentry-compatible:
 *   https://<public_key>@<glitchtip-host>/<project_id>
 */
import * as Sentry from "@sentry/react"

const SENTRY_DSN = import.meta.env.VITE_SENTRY_DSN as string | undefined
const SENTRY_TRACES_SAMPLE_RATE = Number(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE ?? "0.0")
const SENTRY_PROFILES_SAMPLE_RATE = Number(
  import.meta.env.VITE_SENTRY_PROFILES_SAMPLE_RATE ?? "0.0",
)
const SENTRY_ENVIRONMENT =
  (import.meta.env.VITE_SENTRY_ENVIRONMENT as string | undefined) ?? import.meta.env.MODE
const SENTRY_SEND_PII = import.meta.env.VITE_SENTRY_SEND_PII === "true"

let initialized = false

export function initSentry(): void {
  if (initialized) return
  initialized = true

  if (!SENTRY_DSN) {
    // eslint-disable-next-line no-console
    console.debug("[sentry] disabled (no VITE_SENTRY_DSN)")
    return
  }

  Sentry.init({
    dsn: SENTRY_DSN,
    environment: SENTRY_ENVIRONMENT,
    release: `docuintel-frontend@${import.meta.env.VITE_APP_VERSION ?? "0.1.0"}`,
    tracesSampleRate: SENTRY_TRACES_SAMPLE_RATE,
    profilesSampleRate: SENTRY_PROFILES_SAMPLE_RATE,
    sendDefaultPii: SENTRY_SEND_PII,
    // Don't send every console message; rely on the ErrorBoundary.
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration({
        // Capture replays only for errored sessions by default.
        maskAllText: true,
        blockAllMedia: true,
      }),
    ],
    // We do our own filtering in the ErrorBoundary; this just avoids noise.
    beforeSend(event) {
      // Drop events from the dev server in non-development environments.
      if (import.meta.env.PROD === false) return null
      return event
    },
  })
}

export function captureException(error: unknown, extra?: Record<string, unknown>): void {
  if (!initialized || !SENTRY_DSN) return
  Sentry.captureException(error, extra ? { extra } : undefined)
}

export function captureMessage(message: string, level: Sentry.SeverityLevel = "info"): void {
  if (!initialized || !SENTRY_DSN) return
  Sentry.captureMessage(message, level)
}

/** Re-export the Sentry ErrorBoundary so consumers don't need to import the SDK directly. */
export const SentryErrorBoundary = Sentry.ErrorBoundary
