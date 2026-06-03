/// <reference types="vitest" />
import path from "node:path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Canonical versioned API: keep the /api/v1 prefix when proxying.
      "/api/v1": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Legacy unversioned API: strip the /api prefix so requests land at backend root.
      // Kept for one release to avoid breaking existing scripts/docs. Will be removed
      // when api_v1_prefix is locked in.
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (value) => value.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    css: false,
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/main.tsx"],
      thresholds: {
        lines: 50,
        functions: 50,
        branches: 40,
        statements: 50,
      },
    },
  },
})
