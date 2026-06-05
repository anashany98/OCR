import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

/**
 * Editorial-style line illustrations. Hand-crafted SVGs in a single accent
 * color so they adapt to theme. Use as the `icon` prop of EmptyState.
 */

const STROKE = 1.25

function Frame({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <svg
      viewBox="0 0 200 160"
      fill="none"
      stroke="currentColor"
      strokeWidth={STROKE}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("h-full w-full", className)}
      aria-hidden="true"
    >
      {children}
    </svg>
  )
}

export function EmptyDocumentsIllustration() {
  return (
    <Frame>
      <rect x="42" y="32" width="80" height="100" rx="3" />
      <path d="M122 32 L138 32 L138 108 L122 108" />
      <path d="M58 50 H106 M58 62 H106 M58 74 H94 M58 86 H106 M58 98 H82" />
      <circle cx="156" cy="50" r="3" fill="currentColor" />
    </Frame>
  )
}

export function EmptyTasksIllustration() {
  return (
    <Frame>
      <rect x="36" y="28" width="128" height="20" rx="2" />
      <rect x="36" y="56" width="128" height="20" rx="2" />
      <rect x="36" y="84" width="128" height="20" rx="2" />
      <rect x="36" y="112" width="128" height="20" rx="2" />
      <circle cx="48" cy="38" r="4" />
      <circle cx="48" cy="66" r="4" />
      <circle cx="48" cy="94" r="4" />
      <circle cx="48" cy="122" r="4" />
      <path d="M44 38 L48 42 L54 32" opacity="0.4" />
      <path d="M44 66 L48 70 L54 60" opacity="0.4" />
    </Frame>
  )
}

export function EmptySearchIllustration() {
  return (
    <Frame>
      <circle cx="88" cy="76" r="32" />
      <path d="M112 100 L138 126" />
      <path d="M76 68 H100 M76 76 H100 M76 84 H92" opacity="0.5" />
      <circle cx="150" cy="38" r="4" opacity="0.5" />
      <circle cx="40" cy="120" r="2" fill="currentColor" opacity="0.5" />
    </Frame>
  )
}

export function EmptyInboxIllustration() {
  return (
    <Frame>
      <path d="M36 76 L52 36 H148 L164 76 V124 H36 Z" />
      <path d="M36 76 H68 L80 92 H120 L132 76 H164" />
      <path d="M76 124 V108 M100 124 V108 M124 124 V108" opacity="0.5" />
    </Frame>
  )
}

export function EmptyChatIllustration() {
  return (
    <Frame>
      <path d="M28 36 H172 V108 H100 L80 124 V108 H28 Z" />
      <circle cx="60" cy="72" r="4" />
      <circle cx="80" cy="72" r="4" />
      <circle cx="100" cy="72" r="4" />
      <path d="M130 60 H160 M130 72 H160 M130 84 H148" opacity="0.5" />
    </Frame>
  )
}

export function EmptyReconciliationIllustration() {
  return (
    <Frame>
      <circle cx="64" cy="80" r="22" />
      <circle cx="136" cy="80" r="22" />
      <path d="M86 80 H114" />
      <path d="M104 70 L114 80 L104 90" />
      <path d="M50 70 L40 80 L50 90" />
      <path d="M64 50 V58 M64 102 V110 M34 80 H42 M86 80 H94" opacity="0.5" />
    </Frame>
  )
}

export function EmptyJobsIllustration() {
  return (
    <Frame>
      <rect x="44" y="40" width="112" height="80" rx="4" />
      <path d="M44 60 H156" />
      <circle cx="58" cy="50" r="2" fill="currentColor" />
      <circle cx="68" cy="50" r="2" fill="currentColor" />
      <path d="M64 84 H100" />
      <path d="M64 96 H120" opacity="0.5" />
    </Frame>
  )
}

export function EmptyPlansIllustration() {
  return (
    <Frame>
      <rect x="32" y="32" width="136" height="96" />
      <path d="M32 32 L168 128 M168 32 L32 128" opacity="0.3" />
      <rect x="64" y="56" width="32" height="24" />
      <rect x="104" y="80" width="36" height="20" />
      <path d="M96 56 L96 32 M140 100 L140 128" opacity="0.5" />
    </Frame>
  )
}

export function EmptyInvoicesIllustration() {
  return (
    <Frame>
      <path d="M58 24 H142 L158 40 V136 H58 Z" />
      <path d="M142 24 V40 H158" />
      <path d="M70 60 H146 M70 72 H146 M70 84 H130 M70 100 H110 M70 116 H120" opacity="0.5" />
      <circle cx="142" cy="116" r="10" />
      <path d="M138 116 L141 119 L146 113" />
    </Frame>
  )
}
