import { beforeEach, describe, expect, it, vi } from "vitest"

const sentryMocks = vi.hoisted(() => ({
  init: vi.fn(),
  captureException: vi.fn(),
  captureMessage: vi.fn(),
  isolationScope: vi.fn(),
  browserTracingIntegration: vi.fn(() => ({ name: "BrowserTracing" })),
  replayIntegration: vi.fn(() => ({ name: "Replay" })),
  ErrorBoundary: function SentryErrorBoundary() {
    return null
  },
}))

vi.mock("@sentry/react", () => ({
  init: sentryMocks.init,
  captureException: sentryMocks.captureException,
  captureMessage: sentryMocks.captureMessage,
  isolationScope: sentryMocks.isolationScope,
  browserTracingIntegration: sentryMocks.browserTracingIntegration,
  replayIntegration: sentryMocks.replayIntegration,
  ErrorBoundary: sentryMocks.ErrorBoundary,
}))

describe("lib/sentry", () => {
  beforeEach(() => {
    vi.resetModules()
    sentryMocks.init.mockReset()
    sentryMocks.captureException.mockReset()
    sentryMocks.captureMessage.mockReset()
    sentryMocks.isolationScope.mockReset()
  })

  it("is a no-op when VITE_SENTRY_DSN is not set", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "")
    const { initSentry } = await import("@/lib/sentry")
    initSentry()
    initSentry() // idempotent
    expect(sentryMocks.init).not.toHaveBeenCalled()
    vi.unstubAllEnvs()
  })

  it("calls Sentry.init with the right config when DSN is set", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://k@glitchtip/1")
    vi.stubEnv("VITE_SENTRY_TRACES_SAMPLE_RATE", "0.1")
    vi.stubEnv("VITE_SENTRY_PROFILES_SAMPLE_RATE", "0.0")
    vi.stubEnv("VITE_SENTRY_ENVIRONMENT", "ci")

    const { initSentry } = await import("@/lib/sentry")
    initSentry()

    expect(sentryMocks.init).toHaveBeenCalledTimes(1)
    const config = sentryMocks.init.mock.calls[0][0]
    expect(config.dsn).toBe("https://k@glitchtip/1")
    expect(config.environment).toBe("ci")
    expect(config.tracesSampleRate).toBe(0.1)
    expect(config.integrations).toBeDefined()
    vi.unstubAllEnvs()
  })

  it("captureException is a no-op when Sentry is disabled", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "")
    const { captureException } = await import("@/lib/sentry")
    captureException(new Error("boom"))
    expect(sentryMocks.captureException).not.toHaveBeenCalled()
    vi.unstubAllEnvs()
  })

  it("captureMessage is a no-op when Sentry is disabled", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "")
    const { captureMessage } = await import("@/lib/sentry")
    captureMessage("hello", "warning")
    expect(sentryMocks.captureMessage).not.toHaveBeenCalled()
    vi.unstubAllEnvs()
  })
})
