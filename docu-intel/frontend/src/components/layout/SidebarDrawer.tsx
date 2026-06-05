import { useEffect, useRef } from "react"
import { FileText, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { SidebarNav } from "./Sidebar"

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Slide-in navigation drawer. Replaces the persistent sidebar.
 *
 * Open: dispatched event "docu-intel:open-sidebar" or pressing Cmd/Ctrl+B.
 * Close: ESC, click backdrop, or click nav item.
 */
export function SidebarDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  // Lock body scroll while open
  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = previous
    }
  }, [open])

  // Focus the panel when opened, restore focus on close
  useEffect(() => {
    if (!open) return
    const previousActive = document.activeElement as HTMLElement | null
    closeButtonRef.current?.focus()
    return () => {
      previousActive?.focus?.()
    }
  }, [open])

  // ESC closes
  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key === "Tab" && panelRef.current) {
        // Simple focus trap: wrap inside the panel
        const focusables = panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)
        if (!focusables.length) return
        const first = focusables[0]
        const last = focusables[focusables.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50">
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Cerrar menú"
        onClick={onClose}
        className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-fade-in"
        tabIndex={-1}
      />

      {/* Panel */}
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Menú de navegación"
        className={cn(
          "absolute inset-y-0 left-0 flex w-[288px] max-w-[85vw] flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar-bg)] text-[var(--sidebar-text)] shadow-2xl",
          "animate-slide-in-right",
        )}
      >
        {/* Header: brand + close button */}
        <div className="flex h-14 items-center gap-2.5 border-b border-[var(--sidebar-border)] px-3">
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-[var(--accent)] text-white shadow-md">
            <FileText className="h-4 w-4" aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="font-display text-[15px] font-medium leading-tight tracking-tight text-[var(--sidebar-text)]">
              Docu-Intel
            </p>
            <p className="truncate text-[10px] uppercase tracking-[0.12em] text-[var(--sidebar-muted)]">
              Operación documental
            </p>
          </div>
          <Button
            ref={closeButtonRef}
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-8 w-8 text-[var(--sidebar-muted)] hover:text-[var(--sidebar-text)]"
            aria-label="Cerrar menú"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Nav (scrollable) */}
        <div className="flex-1 overflow-y-auto">
          <SidebarNav embedded onNavigate={onClose} />
        </div>
      </aside>
    </div>
  )
}

/**
 * Hook + global event helper for opening the drawer.
 * Mounts once at app root; listens for the custom event and forwards to
 * the open handler.
 */
export function useSidebarDrawerHotkey(setter: (open: boolean) => void) {
  useEffect(() => {
    function onOpen() {
      setter(true)
    }
    function onToggle(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
        event.preventDefault()
        // Toggle is handled by the parent (we just dispatch open here).
        // The parent's state decides whether to actually open.
        setter(true)
      }
    }
    window.addEventListener("docu-intel:open-sidebar", onOpen)
    window.addEventListener("keydown", onToggle)
    return () => {
      window.removeEventListener("docu-intel:open-sidebar", onOpen)
      window.removeEventListener("keydown", onToggle)
    }
  }, [setter])
}
