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
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { useDensity } from "@/hooks/useDensity"
import { CommandPalette } from "@/components/layout/CommandPalette"
import { SidebarNav } from "@/components/layout/Sidebar"
import { SidebarDrawer, useSidebarDrawerHotkey } from "@/components/layout/SidebarDrawer"
import { ThemeToggle } from "@/components/layout/ThemeToggle"
import { useAuth } from "@/hooks/useAuth"
import { useWorkInboxCount } from "@/hooks/useWorkInboxCount"
import { titleForPath } from "@/navigation/config"
import { cn } from "@/lib/utils"

const SIDEBAR_WIDTH = 240
const SIDEBAR_COLLAPSED_WIDTH = 56
const SIDEBAR_STORAGE_KEY = "docu-intel:sidebar"

function getInitialCollapsed(): boolean {
  try { return localStorage.getItem(SIDEBAR_STORAGE_KEY) === "collapsed" } catch { return false }
}

export function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [query, setQuery] = useState("")
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(getInitialCollapsed)

  const health = useQuery({ queryKey: ["system-health"], queryFn: api.systemHealth, refetchInterval: 30000, refetchIntervalInBackground: false })
  const inbox = useWorkInboxCount()
  const inboxCount = inbox.data?.count ?? 0
  const pageTitle = titleForPath(location.pathname)

  const toggleSidebar = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev
      try { localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? "collapsed" : "expanded") } catch {}
      return next
    })
  }, [])

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

  const systemOk = health.data?.status === "ok" || health.data?.status === "ready"
  const { density, toggleDensity } = useDensity()

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex h-screen overflow-hidden bg-[var(--bg-canvas)]">
        {/* ── Sidebar ── */}
        <aside
          className="hidden flex-shrink-0 flex-col border-r border-[var(--sidebar-border)] text-[var(--sidebar-text)] transition-[width] duration-200 ease-out lg:flex"
          style={{ width: collapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_WIDTH, background: "linear-gradient(180deg, var(--sidebar-bg) 0%, #070b14 100%)" }}
        >
          {/* Brand */}
          <div className={cn("flex h-14 items-center border-b border-[var(--sidebar-border)]", collapsed ? "justify-center px-2" : "gap-3 px-4")}>
            <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-[var(--accent)] text-white shadow-lg shadow-[var(--accent)]/25">
              <FileText className="h-4 w-4" />
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <p className="text-[14px] font-bold leading-tight text-white">Docu-Intel</p>
                <p className="truncate text-[9px] uppercase tracking-[0.15em] text-[var(--sidebar-muted)]">Operación documental</p>
              </div>
            )}
          </div>

          {/* Nav */}
          <div className="flex-1 overflow-y-auto py-2">
            <SidebarNav collapsed={collapsed} inboxCount={inboxCount} />
          </div>

          {/* Collapse */}
          <div className="border-t border-[var(--sidebar-border)] p-1.5">
            <button
              onClick={toggleSidebar}
              className={cn("flex w-full items-center gap-2 rounded-md py-1.5 text-[11px] transition-colors", collapsed ? "justify-center px-0" : "px-3", "text-[var(--sidebar-muted)] hover:bg-[var(--sidebar-active-bg)] hover:text-[var(--sidebar-text)]")}
              aria-label={collapsed ? "Expandir" : "Contraer"}
            >
              {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <><PanelLeftClose className="h-4 w-4" /><span>Contraer</span></>}
            </button>
          </div>
        </aside>

        {/* ── Main ── */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Topbar */}
          <header className="sticky top-0 z-20 flex h-12 items-center gap-3 border-b border-[var(--border)] bg-[var(--bg-surface)] px-4 shadow-xs">
            <button onClick={() => setDrawerOpen(true)} className="flex h-8 w-8 items-center justify-center rounded-md text-[var(--text-secondary)] hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-primary)] lg:hidden" aria-label="Menú">
              <Menu className="h-4 w-4" />
            </button>

            <h1 className="truncate text-[13px] font-semibold text-[var(--text-primary)]">{pageTitle}</h1>

            <div className="flex-1" />

            {inboxCount > 0 && (
              <Badge variant="warning" className="hidden cursor-pointer items-center gap-1 text-[10px] sm:inline-flex" onClick={() => navigate("/work-inbox")}
                aria-label={`${inboxCount} tareas pendientes`}>
                {inboxCount} tareas
              </Badge>
            )}

            <button
              type="button"
              onClick={() => window.dispatchEvent(new Event("docu-intel:open-command-palette"))}
              className="hidden h-8 items-center gap-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 text-[11px] text-[var(--text-muted)] hover:bg-[var(--bg-surface-hover)] md:inline-flex"
              aria-label="Buscar"
            >
              <CommandIcon className="h-3 w-3" />
              <span>Buscar</span>
              <kbd className="ml-0.5 rounded border border-[var(--border)] bg-[var(--bg-surface)] px-1 font-mono text-[9px]">⌘K</kbd>
            </button>

            <form className="relative md:hidden" onSubmit={onSearch}>
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--text-muted)]" />
              <Input aria-label="Buscar" className="h-8 w-28 rounded border-[var(--border)] bg-[var(--bg-surface-2)] pl-7 pr-2 text-[12px]" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar…" />
            </form>

            <div className="hidden items-center gap-1 sm:flex">
              <span className={cn("h-1.5 w-1.5 rounded-full", systemOk ? "bg-[var(--success)]" : "bg-[var(--warning)]")} />
              <span className="text-[10px] text-[var(--text-muted)]">OK</span>
            </div>

            <ThemeToggle />

            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={toggleDensity}
                  className="flex h-8 w-8 items-center justify-center rounded-md text-[var(--text-secondary)] hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-primary)]"
                  aria-label={`Densidad: ${density === "compact" ? "compacta" : "cómoda"}`}
                >
                  {density === "compact" ? (
                    <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><line x1="2" y1="3" x2="14" y2="3" /><line x1="2" y1="7" x2="14" y2="7" /><line x1="2" y1="11" x2="14" y2="11" /><line x1="2" y1="15" x2="14" y2="15" /></svg>
                  ) : (
                    <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><line x1="2" y1="3" x2="14" y2="3" /><line x1="2" y1="8" x2="14" y2="8" /><line x1="2" y1="13" x2="14" y2="13" /></svg>
                  )}
                </button>
              </TooltipTrigger>
              <TooltipContent>{density === "compact" ? "Modo compacto" : "Modo cómodo"}</TooltipContent>
            </Tooltip>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="flex items-center gap-1.5 rounded-md px-1.5 py-1 hover:bg-[var(--bg-surface-2)]" aria-label="Usuario">
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--accent)] text-[11px] font-bold text-white">{user?.name?.charAt(0)?.toUpperCase() ?? "U"}</div>
                  <span className="hidden text-[12px] text-[var(--text-secondary)] sm:inline">{user?.name?.split(" ")[0]}</span>
                  <ChevronDown className="hidden h-3 w-3 text-[var(--text-muted)] sm:block" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-44">
                <div className="px-2 py-1.5">
                  <p className="text-[12px] font-medium">{user?.name}</p>
                  <p className="text-[10px] text-[var(--text-muted)]">{user?.email}</p>
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => navigate("/admin")} className="text-[12px]"><Settings className="mr-2 h-3.5 w-3.5" /> Admin</DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={logout} className="text-[12px] text-[var(--danger)]"><LogOut className="mr-2 h-3.5 w-3.5" /> Salir</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </header>

          {/* Content */}
          <main className="flex-1 overflow-y-auto p-4 lg:p-5">
            <Outlet />
          </main>
        </div>

        <SidebarDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
        <CommandPalette />
      </div>
    </TooltipProvider>
  )
}
