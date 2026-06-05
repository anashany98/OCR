import type { Config } from "tailwindcss"

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "var(--border)",
        "border-2": "var(--border-2)",
        "border-3": "var(--border-3)",
        background: "var(--bg-base)",
        foreground: "var(--text-primary)",
        surface: "var(--bg-surface)",
        "surface-2": "var(--bg-surface-2)",
        "surface-hover": "var(--bg-surface-hover)",

        // Editorial ink scale
        ink: {
          deep: "var(--ink-deep)",
          DEFAULT: "var(--ink)",
          soft: "var(--ink-soft)",
        },

        // Terracotta accent
        primary: {
          DEFAULT: "var(--accent)",
          hover: "var(--accent-hover)",
          soft: "var(--accent-soft)",
          light: "var(--accent-light)",
          faint: "var(--accent-faint)",
          foreground: "var(--primary-foreground)",
        },
        // Legacy aliases for backward compat
        emerald: {
          DEFAULT: "var(--positive)",
          light: "var(--positive-light)",
        },
        amber: {
          DEFAULT: "var(--warning)",
          light: "var(--warning-light)",
        },
        rose: {
          DEFAULT: "var(--danger)",
          light: "var(--danger-light)",
        },
        sky: {
          DEFAULT: "var(--info)",
          light: "var(--info-light)",
        },
        card: {
          DEFAULT: "var(--bg-surface)",
          foreground: "var(--text-primary)",
        },
        muted: {
          DEFAULT: "var(--bg-surface-2)",
          foreground: "var(--text-secondary)",
        },
        destructive: {
          DEFAULT: "var(--danger)",
          foreground: "white",
        },
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
        "2xl": "var(--radius-2xl)",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        paper: "var(--shadow-paper)",
      },
      fontFamily: {
        display: ["'Fraunces'", "ui-serif", "Georgia", "serif"],
        sans: ["'Inter'", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.16, 1, 0.3, 1)",
        "in-out": "cubic-bezier(0.65, 0, 0.35, 1)",
      },
      transitionDuration: {
        fast: "150ms",
        base: "250ms",
        slow: "400ms",
      },
      fontSize: {
        "2xs": ["11px", { lineHeight: "16px" }],
        xs: ["12px", { lineHeight: "18px" }],
        sm: ["13px", { lineHeight: "20px" }],
        base: ["14px", { lineHeight: "22px" }],
        lg: ["17px", { lineHeight: "26px" }],
        xl: ["20px", { lineHeight: "28px" }],
        "2xl": ["26px", { lineHeight: "32px" }],
        "3xl": ["34px", { lineHeight: "40px" }],
        "4xl": ["44px", { lineHeight: "50px" }],
        "5xl": ["56px", { lineHeight: "62px" }],
      },
      keyframes: {
        fadeInUp: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        fadeIn: {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        slideInRight: {
          from: { opacity: "0", transform: "translateX(8px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
      },
      animation: {
        "fade-in-up": "fadeInUp 250ms cubic-bezier(0.16, 1, 0.3, 1) both",
        "fade-in": "fadeIn 250ms cubic-bezier(0.16, 1, 0.3, 1) both",
        "slide-in-right": "slideInRight 250ms cubic-bezier(0.16, 1, 0.3, 1) both",
        shimmer: "shimmer 1.5s infinite",
      },
    },
  },
  plugins: [],
} satisfies Config
