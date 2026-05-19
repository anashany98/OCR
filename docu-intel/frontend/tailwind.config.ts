import type { Config } from "tailwindcss"

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "var(--border)",
        "border-2": "var(--border-2)",
        background: "var(--bg-base)",
        foreground: "var(--text-primary)",
        surface: "var(--bg-surface)",
        "surface-2": "var(--bg-surface-2)",
        "surface-hover": "var(--bg-surface-hover)",
        primary: {
          DEFAULT: "var(--primary)",
          hover: "var(--primary-hover)",
          light: "var(--primary-light)",
          foreground: "var(--primary-foreground)",
        },
        emerald: {
          DEFAULT: "var(--emerald)",
          light: "var(--emerald-light)",
        },
        amber: {
          DEFAULT: "var(--amber)",
          light: "var(--amber-light)",
        },
        rose: {
          DEFAULT: "var(--rose)",
          light: "var(--rose-light)",
        },
        sky: {
          DEFAULT: "var(--sky)",
          light: "var(--sky-light)",
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
          DEFAULT: "var(--rose)",
          foreground: "white",
        },
      },
      borderRadius: {
        sm: "var(--radius-sm)",
        md: "var(--radius-md)",
        lg: "var(--radius-lg)",
        xl: "var(--radius-xl)",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
      },
      fontFamily: {
        sans: ["'Instrument Sans'", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      transitionDuration: {
        fast: "150ms",
        base: "250ms",
      },
      fontSize: {
        "2xs": ["11px", { lineHeight: "16px" }],
        xs: ["13px", { lineHeight: "18px" }],
        sm: ["14px", { lineHeight: "20px" }],
        base: ["14px", { lineHeight: "22px" }],
        lg: ["18px", { lineHeight: "26px" }],
        xl: ["22px", { lineHeight: "28px" }],
        "2xl": ["28px", { lineHeight: "34px" }],
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
      },
      animation: {
        "fade-in-up": "fadeInUp 250ms cubic-bezier(0.16, 1, 0.3, 1) both",
        "fade-in": "fadeIn 250ms cubic-bezier(0.16, 1, 0.3, 1) both",
        shimmer: "shimmer 1.5s infinite",
      },
    },
  },
  plugins: [],
} satisfies Config