import { FormEvent, useState } from "react"
import { Outlet, useMatches, useNavigate, type UIMatch } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ChevronDown, Command as CommandIcon, FileText, LogOut, Menu, Search } from "lucide-react"

import { api } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { CommandPalette } from "@/components/layout/CommandPalette"
import { SidebarNav } from "@/components/layout/Sidebar"
import { SidebarDrawer, useSidebarDrawerHotkey } from "@/components/layout/SidebarDrawer"
import { ThemeToggle } from "@/components/layout/ThemeToggle"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

export function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const matches = useMatches()
  const [query, setQuery] = useState("")
  const [drawerOpen, setDrawerOpen] = useState(false)
  const health = useQuery({ queryKey: ["system-health"], queryFn: api.systemHealth, refetchInterval: 30000 })
  const inbox = useQuery({ queryKey: ["work-inbox-count"], queryFn: () => api.workInboxCount(), refetchInterval: 30000 })

  const inboxCount = inbox.data?.count ?? 0

  const pageTitle = getPageTitle(matches)

  function setMobileDrawer(open: boolean) {
    if (open && typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches) return
    setDrawerOpen(open)
  }

  useSidebarDrawerHotkey(setMobileDrawer)

  function onSearch(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (trimmed) navigate("/search?q=" + encodeURIComponent(trimmed))
    setQuery("")
  }

  const systemStatus = health.data?.status === "ok" || health.data?.status === "ready"

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg-base)]">
      <aside className="hidden w-[260px] flex-shrink-0 flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar-bg)] text-[var(--sidebar-text)] lg:flex">
        <div className="flex h-12 items-center gap-2.5 border-b border-[var(--sidebar-border)] px-3">
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
        </div>
        <div className="flex-1 overflow-y-auto">
          <SidebarNav />
        </div>
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Topbar */}
        <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg-surface)]/95 backdrop-blur-sm">
          <div className="flex h-12 items-center gap-3 px-4">
            <button
              onClick={() => setDrawerOpen(true)}
              className="flex h-8 w-8 items-center justify-center rounded-md text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-primary)] lg:hidden"
              aria-label="Abrir menú de navegación"
              title="Menú (⌘B)"
            >
              <Menu className="h-5 w-5" />
            </button>

            {/* Page title */}
            <h1 className="truncate text-[14px] font-semibold tracking-tight text-[var(--text-primary)]">{pageTitle}</h1>

            {/* Spacer */}
            <div className="flex-1" />

            {/* Tareas badge */}
            {inboxCount > 0 && (
              <Badge
                variant="warning"
                className="hidden cursor-pointer items-center gap-1 sm:inline-flex"
                onClick={() => navigate("/work-inbox")}
              >
                <span>{inboxCount} {inboxCount === 1 ? "tarea" : "tareas"}</span>
              </Badge>
            )}

            {/* Command palette trigger (Cmd+K) */}
            <button
              type="button"
              onClick={() => window.dispatchEvent(new Event("docu-intel:open-command-palette"))}
              className="hidden h-8 items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--bg-surface-2)] px-2.5 text-[12px] text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-surface-hover)] md:inline-flex"
              aria-label="Abrir paleta de comandos"
              title="Buscar páginas y acciones (Ctrl+K)"
            >
              <CommandIcon className="h-3.5 w-3.5" />
              <span>Buscar…</span>
              <kbd className="ml-1 rounded border border-[var(--border)] bg-[var(--bg-surface)] px-1 font-mono text-[10px] text-[var(--text-muted)]">⌘K</kbd>
            </button>

            {/* Search fallback (mobile) */}
            <form className="relative md:hidden" onSubmit={onSearch}>
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
              <Input
                aria-label="Buscar documentos"
                className="h-8 w-32 rounded-md border-[var(--border)] bg-[var(--bg-surface-2)] pl-8 pr-3 text-[13px] placeholder:text-[var(--text-muted)] focus:border-[var(--primary)] focus:bg-[var(--bg-surface)] sm:w-48"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar…"
              />
            </form>

            {/* Status indicator */}
            <div className="hidden items-center gap-1.5 sm:flex">
              <span className={cn("h-1.5 w-1.5 rounded-full", systemStatus ? "bg-[var(--positive)]" : "bg-[var(--warning)]")} />
              <span className="text-[11px] text-[var(--text-muted)]">Sistema</span>
            </div>

            {/* Theme toggle */}
            <ThemeToggle />

            {/* User menu */}
            <div className="relative">
              <button
                className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[13px] transition-colors hover:bg-[var(--bg-surface-2)]"
                aria-label="Menú de usuario"
                title={user?.name}
              >
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--accent-faint)] text-[11px] font-semibold text-[var(--accent)]">
                  {user?.name?.charAt(0)?.toUpperCase() ?? "U"}
                </div>
                <span className="hidden text-[var(--text-secondary)] sm:inline">{user?.name?.split(" ")[0]}</span>
                <ChevronDown className="hidden h-3 w-3 text-[var(--text-muted)] sm:block" />
              </button>
            </div>

            {/* Logout */}
            <Button
              variant="ghost"
              size="icon"
              onClick={logout}
              className="h-8 w-8 text-[var(--text-muted)] hover:text-[var(--danger)]"
              title="Cerrar sesión"
              aria-label="Cerrar sesión"
            >
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        </header>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto px-4 py-5 lg:px-6">
          <Outlet />
        </main>
      </div>

      <SidebarDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
      <CommandPalette />
    </div>
  )
}

type PageTitleHandle = {
  title?: string
}

function getPageTitle(matches: UIMatch<unknown, unknown>[]): string {
  for (const match of [...matches].reverse()) {
    const title = (match.handle as PageTitleHandle | undefined)?.title
    if (title) return title
  }
  return "Docu-Intel"
}
