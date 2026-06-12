import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// ----- Date formatting -----------------------------------------------------

export function formatDate(value: string | null | undefined) {
  if (!value) return "-"
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value))
}

/** Short date (e.g. "5 jun"). Used in compact lists. */
export function formatDateShort(value: string | null | undefined) {
  if (!value) return "-"
  return new Intl.DateTimeFormat("es-ES", {
    day: "numeric",
    month: "short",
  }).format(new Date(value))
}

/** Long date + time, e.g. "5 de junio de 2026, 14:32". */
export function formatDateLong(value: string | null | undefined) {
  if (!value) return "-"
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "long",
    timeStyle: "short",
  }).format(new Date(value))
}

// ----- Money formatting ----------------------------------------------------

/**
 * Format a number as EUR using Spanish locale (1.245,60 €). Returns "-" for
 * null/undefined. Replaces ad-hoc `value.toFixed(2) + " €"` snippets that
 * produced English-style numbers (1245.60 €).
 */
export function formatMoney(
  value: number | null | undefined,
  options: Intl.NumberFormatOptions = { style: "currency", currency: "EUR" },
) {
  if (value == null) return "-"
  return new Intl.NumberFormat("es-ES", options).format(value)
}

// ----- File sizes ----------------------------------------------------------

export function formatBytes(value: number) {
  if (!value) return "0 B"
  const units = ["B", "KB", "MB", "GB"]
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

// ----- Compact numbers -----------------------------------------------------

/** Format large numbers with k/M suffix for metric tiles. 1234 → "1,2 k". */
export function formatCompact(value: number | null | undefined, fractionDigits = 1) {
  if (value == null) return "-"
  return new Intl.NumberFormat("es-ES", {
    notation: "compact",
    maximumFractionDigits: fractionDigits,
  }).format(value)
}

// ----- Truncate ------------------------------------------------------------

/** Truncate a string with ellipsis. */
export function truncate(value: string, max: number) {
  if (value.length <= max) return value
  return value.slice(0, Math.max(0, max - 1)) + "…"
}
