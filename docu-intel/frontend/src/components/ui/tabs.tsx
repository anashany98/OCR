/** Minimal Tabs primitive. Lightweight shadcn-style implementation
 * that does not pull in @radix-ui/react-tabs. */
import * as React from "react"

import { cn } from "@/lib/utils"

interface TabsContextValue {
  value: string
  setValue: (value: string) => void
}

const TabsContext = React.createContext<TabsContextValue | null>(null)

function useTabsContext(component: string) {
  const context = React.useContext(TabsContext)
  if (!context) {
    throw new Error(`${component} must be used inside <Tabs>`)
  }
  return context
}

interface TabsProps {
  defaultValue: string
  value?: string
  onValueChange?: (value: string) => void
  className?: string
  children: React.ReactNode
}

export function Tabs({
  defaultValue,
  value: controlled,
  onValueChange,
  className,
  children,
}: TabsProps) {
  const [internal, setInternal] = React.useState(defaultValue)
  const value = controlled ?? internal
  const setValue = React.useCallback(
    (next: string) => {
      if (controlled === undefined) setInternal(next)
      onValueChange?.(next)
    },
    [controlled, onValueChange],
  )
  return (
    <TabsContext.Provider value={{ value, setValue }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  )
}

export function TabsList({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "inline-flex h-10 items-center justify-start gap-1 rounded-md border border-[var(--border-2)] bg-[var(--bg-surface-2)] p-1 text-[var(--text-secondary)]",
        className,
      )}
      role="tablist"
    >
      {children}
    </div>
  )
}

interface TabsTriggerProps {
  value: string
  className?: string
  children: React.ReactNode
}

export function TabsTrigger({ value, className, children }: TabsTriggerProps) {
  const { value: active, setValue } = useTabsContext("TabsTrigger")
  const selected = active === value
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      onClick={() => setValue(value)}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium transition-colors",
        selected
          ? "bg-[var(--bg-surface)] text-[var(--text-primary)] shadow-sm"
          : "hover:text-[var(--text-primary)]",
        className,
      )}
    >
      {children}
    </button>
  )
}

export function TabsContent({
  value,
  className,
  children,
}: {
  value: string
  className?: string
  children: React.ReactNode
}) {
  const { value: active } = useTabsContext("TabsContent")
  if (active !== value) return null
  return (
    <div className={cn("mt-4", className)} role="tabpanel">
      {children}
    </div>
  )
}
