import { FormEvent, useCallback, useState } from "react"
import { Outlet, useLocation, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  ChevronDown,
  Command as CommandIcon,
  FileText,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
} from "lucide-react"

import { api } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { TooltipProvider } from "@/components/ui/tooltip"
import { CommandPalette } from "@/components/layout/CommandPalette"
import { SidebarNav } from "@/components/layout/Sidebar"
import { SidebarDrawer, useSidebarDrawerHotkey } from "@/components/layout/SidebarDrawer"
import { ThemeToggle } from "@/components/layout/ThemeToggle"
import { useAuth } from "@/hooks/useAuth"
import { useWorkInboxCount } from "@/hooks/useWorkInboxCount"
import { titleForPath } from "@/navigation/config"
import { cn } from "@/lib/utils"

const SIDEBAR_WIDTH = 260
const SIDEBAR_COLLAPSED_WIDTH = 64
const SIDEBAR_STORAGE_KEY = "docu-intel:sidebar"

function getInitialCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) === "collapsed"
  } catch {
    return false
  }
}

export function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [query, setQuery] = useState("")
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(getInitialCollapsed)

  const health = useQuery({
    queryKey: ["system-health"],
    queryFn: api.systemHealth,
    refetchInterval: 30000,
    refetchIntervalInBackground: false,
  })
  const inbox = useWorkInboxCount()
  const inboxCount = inbox.data?.count ?? 0

  const pageTitle = titleForPath(location.pathname)

  const toggleSidebar = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? "collapsed" : "expanded")
      } catch {
        // localStorage not available
      }
      return next
    })
  }, [])

  function setMobileDrawer(open: boolean) {
    if (open && typeof window !== "undefined" && window.matchMedia("(min-width: 1024px)").matches)
      return
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
    <TooltipProvider delayDuration={300}>
      <div className="flex h-screen overflow-hidden bg-[var(--bg-canvas)]">
        {/* Desktop sidebar */}
        <aside
          className={cn(
            "hidden flex-shrink-0 flex-col border-r border-[var(--sidebar-border)] text-[var(--sidebar-text)] transition-all duration-base ease-out lg:flex",
          )}
          style={{ width: collapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_WIDTH, background: "linear-gradient(180deg, var(--sidebar-bg) 0%, #0a0f1e 100%)" }}
        >
          {/* Sidebar header */}
          <div className="flex h-14 items-center gap-3 border-b border-[var(--sidebar-border)] px-4">
            <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-[var(--accent)] text-white shadow-lg shadow-[var(--accent)]/20">
              <FileText className="h-4.5 w-4.5" aria-hidden="true" />
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <p className="text-[15px] font-bold leading-tight tracking-tight text-white">
                  Docu-Intel
                </p>
                <p className="truncate text-[10px] uppercase tracking-[0.12em] text-[var(--sidebar-muted)]">
                  Operación documental
                </p>
              </div>
            )}
          </div>

          {/* Sidebar nav */}
          <div className="flex-1 overflow-y-auto">
            <SidebarNav collapsed={collapsed} inboxCount={inboxCount} />
          </div>

          {/* Collapse toggle */}
          <div className="border-t border-[var(--sidebar-border)] p-2">
            <button
              onClick={toggleSidebar}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-[12px] transition-colors",
                "text-[var(--sidebar-muted)] hover:bg-[var(--sidebar-active-bg)] hover:text-[var(--sidebar-text)]",
              )}
              aria-label={collapsed ? "Expandir barra lateral" : "Contraer barra lateral"}
            >
              {collapsed ? (
                <PanelLeftOpen className="h-4 w-4 flex-shrink-0" />
              ) : (
                <>
                  <PanelLeftClose className="h-4 w-4 flex-shrink-0" />
                  <span>Contraer</span>
                </>
              )}
            </button>
          </div>
        </aside>

        {/* Main area */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Topbar */}
          <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--bg-surface)] shadow-xs">
            <div className="flex h-14 items-center gap-3 px-5">
              {/* Mobile menu */}
              <button
                onClick={() => setDrawerOpen(true)}
                className="flex h-8 w-8 items-center justify-center rounded-md text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-primary)] lg:hidden"
                aria-label="Abrir menú de navegación"
                title="Menú (⌘B)"
              >
                <Menu className="h-5 w-5" />
              </button>

              {/* Page title */}
              <h1 className="truncate text-[14px] font-semibold tracking-tight text-[var(--text-primary)]">
                {pageTitle}
              </h1>

              {/* Spacer */}
              <div className="flex-1" />

              {/* Tareas badge */}
              {inboxCount > 0 && (
                <Badge
                  variant="warning"
                  className="hidden cursor-pointer items-center gap-1 sm:inline-flex"
                  onClick={() => navigate("/work-inbox")}
                  aria-label={`${inboxCount} ${inboxCount === 1 ? "tarea pendiente" : "tareas pendientes"}`}
                >
                  <span>
                    {inboxCount} {inboxCount === 1 ? "tarea" : "tareas"}
                  </span>
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
                <kbd className="ml-1 rounded border border-[var(--border)] bg-[var(--bg-surface)] px-1 font-mono text-[10px] text-[var(--text-muted)]">
                  ⌘K
                </kbd>
              </button>

              {/* Search fallback (mobile) */}
              <form className="relative md:hidden" onSubmit={onSearch}>
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
                <Input
                  aria-label="Buscar documentos"
                  className="h-8 w-32 rounded-md border-[var(--border)] bg-[var(--bg-surface-2)] pl-8 pr-3 text-[13px] placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] focus:bg-[var(--bg-surface)] sm:w-48"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Buscar…"
                />
              </form>

              {/* Status indicator */}
              <div className="hidden items-center gap-1.5 sm:flex">
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    systemStatus ? "bg-[var(--success)]" : "bg-[var(--warning)]",
                  )}
                />
                <span className="text-[11px] text-[var(--text-muted)]">Sistema</span>
              </div>

              {/* Theme toggle */}
              <ThemeToggle />

              {/* User dropdown */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[13px] transition-colors hover:bg-[var(--bg-surface-2)]"
                    aria-label="Menú de usuario"
                  >
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--accent)] text-[12px] font-bold text-white shadow-sm">
                      {user?.name?.charAt(0)?.toUpperCase() ?? "U"}
                    </div>
                    <span className="hidden text-[var(--text-secondary)] sm:inline">
                      {user?.name?.split(" ")[0]}
                    </span>
                    <ChevronDown className="hidden h-3 w-3 text-[var(--text-muted)] sm:block" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <div className="px-2 py-1.5">
                    <p className="text-[13px] font-medium text-[var(--text-primary)]">{user?.name}</p>
                    <p className="text-[11px] text-[var(--text-muted)]">{user?.email}</p>
                  </div>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => navigate("/admin")}>
                    <Settings className="mr-2 h-4 w-4" />
                    Administración
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={logout} className="text-[var(--danger)]">
                    <LogOut className="mr-2 h-4 w-4" />
                    Cerrar sesión
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
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
    </TooltipProvider>
  )
}
