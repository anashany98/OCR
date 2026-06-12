// ESLint 9 flat config. Replaces the legacy .eslintrc.cjs
// (which v9 silently ignores). The shape mirrors the previous
// rules: recommended + typescript + react + react-hooks, with
// the same overrides for unused vars and explicit any.
//
// Flat-config migration notes:
//   * The "env" object is gone; we use the ``globals`` package
//     to declare browser/node globals.
//   * Each plugin is wrapped in a flat-config-aware call
//     (``tseslint.config``, ``react.config``,
//     ``reactHooks.config``) so it can declare its own
//     file globs and parsers.
//   * ``parserOptions`` is per-language now; we only need
//     TypeScript here.

import js from "@eslint/js"
import tseslint from "typescript-eslint"
import reactPlugin from "eslint-plugin-react"
import reactHooks from "eslint-plugin-react-hooks"
import globals from "globals"

export default [
  // Lint every TS/TSX file in the project. ``dist``,
  // ``node_modules``, ``coverage`` and the build configs are
  // excluded globally.
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "coverage/**",
      "*.config.js",
      "*.config.ts",
    ],
  },

  // The recommended baseline + TS recommended. Each plugin's
  // ``flat/recommended`` config registers itself with the
  // appropriate file globs.
  js.configs.recommended,
  ...tseslint.configs.recommended,
  reactPlugin.configs.flat.recommended,
  reactPlugin.configs.flat["jsx-runtime"],

  // ``eslint-plugin-react-hooks`` ships a flat config but the
  // export is a single object, not an array, so we wire it
  // up by hand instead of spreading.
  {
    plugins: {
      "react-hooks": reactHooks,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  },

  {
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    settings: {
      react: { version: "18.3" },
    },
    rules: {
      // The legacy config disabled these two for the
      // Vite + React 17+ JSX runtime. Carry that over.
      "react/react-in-jsx-scope": "off",
      "react/prop-types": "off",
      // Match the legacy override: warn (not error) on
      // unused variables that start with ``_`` and on
      // ``any`` so the gate is informational rather than
      // blocking.
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },
]
