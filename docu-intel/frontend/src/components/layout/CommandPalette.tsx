import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Command } from "cmdk"
import { Search, ShieldAlert } from "lucide-react"

import { useAuth } from "@/hooks/useAuth"
import { NAV_GROUPS, type NavItem } from "@/navigation/config"
import { cn } from "@/lib/utils"

type CommandItem = NavItem & { group: string }

const EXTRA_COMMANDS: CommandItem[] = [
  // The palette offers a couple of cross-cutting shortcuts that aren't in the
  // sidebar nav (e.g. "jump to dashboard alerts"). Kept tiny on purpose.
  {
    to: "/",
    label: "Ver alertas urgentes",
    icon: ShieldAlert as unknown as React.ComponentType<{ className?: string }>,
    group: "General",
    keywords: ["alerta", "critico", "atencion"],
  },
]

const COMMANDS: CommandItem[] = [
  ...NAV_GROUPS.flatMap((group) => group.items.map((item) => ({ ...item, group: group.label }))),
  ...EXTRA_COMMANDS,
]

/**
 * Cmd/Ctrl+K command palette. Filters all top-level routes by label and
 * keyword and lets the user jump with the keyboard.
 *
 * Renders into a Sonner-free modal mounted on the AppShell. Trigger is global
 * Cmd/Ctrl+K (handled internally); the host can also pass `open` to force
 * state (not currently used but kept for future API).
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const navigate = useNavigate()
  const { user } = useAuth()

  // Toggle on Cmd/Ctrl+K
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault()
        setOpen((value) => !value)
      }
    }
    function onCustomOpen() {
      setOpen(true)
    }
    window.addEventListener("keydown", onKeyDown)
    window.addEventListener("docu-intel:open-command-palette", onCustomOpen)
    return () => {
      window.removeEventListener("keydown", onKeyDown)
      window.removeEventListener("docu-intel:open-command-palette", onCustomOpen)
    }
  }, [])

  const visible = useMemo(() => {
    if (!user) return []
    return COMMANDS.filter((cmd) => !cmd.roles?.length || cmd.roles.includes(user.role))
  }, [user])

  function go(to: string) {
    setOpen(false)
    setSearch("")
    navigate(to)
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-[15vh] backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-xl overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <Command label="Paleta de comandos" shouldFilter loop className="flex flex-col">
          <div className="flex items-center gap-2 border-b border-[var(--border)] px-4">
            <Search className="h-4 w-4 text-[var(--text-muted)]" />
            <Command.Input
              autoFocus
              value={search}
              onValueChange={setSearch}
              placeholder="Buscar página, acción o ajuste…"
              className="h-12 w-full bg-transparent text-[14px] outline-none placeholder:text-[var(--text-muted)]"
            />
            <kbd className="hidden rounded border border-[var(--border)] bg-[var(--bg-surface-2)] px-1.5 py-0.5 text-[10px] font-mono text-[var(--text-muted)] sm:inline">
              ESC
            </kbd>
          </div>
          <Command.List className="max-h-[55vh] overflow-y-auto p-2">
            <Command.Empty className="px-3 py-6 text-center text-[13px] text-[var(--text-muted)]">
              Sin resultados. Prueba con otro término.
            </Command.Empty>
            {Array.from(new Set(visible.map((cmd) => cmd.group))).map((group) => {
              const items = visible.filter((cmd) => cmd.group === group)
              if (!items.length) return null
              return (
                <Command.Group
                  key={group}
                  heading={group}
                  className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-[var(--text-muted)]"
                >
                  {items.map((item) => {
                    const Icon = item.icon
                    return (
                      <Command.Item
                        key={item.to}
                        value={`${item.label} ${item.keywords?.join(" ") ?? ""}`}
                        onSelect={() => go(item.to)}
                        className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-[13px] aria-selected:bg-[var(--primary-light)] aria-selected:text-[var(--primary)]"
                      >
                        <Icon className="h-4 w-4 flex-shrink-0 text-[var(--text-muted)]" />
                        <span className="flex-1 truncate">{item.label}</span>
                        <span className="text-[11px] text-[var(--text-muted)] opacity-0 transition-opacity group-aria-selected:opacity-100">
                          ↵
                        </span>
                      </Command.Item>
                    )
                  })}
                </Command.Group>
              )
            })}
          </Command.List>
          <div className="flex items-center justify-between border-t border-[var(--border)] bg-[var(--bg-surface-2)] px-4 py-2 text-[11px] text-[var(--text-muted)]">
            <span>{visible.length} comandos</span>
            <span className="flex items-center gap-3">
              <Hint keys="↑↓">Navegar</Hint>
              <Hint keys="↵">Abrir</Hint>
              <Hint keys="esc">Cerrar</Hint>
            </span>
          </div>
        </Command>
      </div>
    </div>
  )
}

function Hint({ keys, children }: { keys: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1">
      <kbd
        className={cn(
          "rounded border border-[var(--border)] bg-[var(--bg-surface)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]",
        )}
      >
        {keys}
      </kbd>
      <span>{children}</span>
    </span>
  )
}
