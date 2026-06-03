/**
 * Vitest setup file. Runs once before any test in this project.
 *
 * * Registers `@testing-library/jest-dom` matchers (toBeInTheDocument, etc.)
 * * Polyfills `fetch` for happy-dom (jsdom-style environment, but cheap)
 * * Mocks `import.meta.env.VITE_*` defaults so tests don't need a build
 */
import "@testing-library/jest-dom/vitest"
import { afterEach, beforeEach, vi } from "vitest"
import { cleanup } from "@testing-library/react"

// Provide a default base URL so request() calls in tests don't 404.
;(import.meta as unknown as { env: Record<string, string> }).env = {
  ...(import.meta as unknown as { env: Record<string, string> }).env,
  VITE_API_BASE_URL: "http://test.local/api/v1",
  MODE: "test",
}

// Reset the DOM and mocks after each test.
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

// Quiet down console.error from React on expected error-boundary tests.
const originalError = console.error
beforeEach(() => {
  console.error = (...args: unknown[]) => {
    const message = typeof args[0] === "string" ? args[0] : ""
    if (message.includes("not wrapped in act(")) return
    if (message.includes("ErrorBoundary caught:")) return
    originalError(...args)
  }
})
afterEach(() => {
  console.error = originalError
})
