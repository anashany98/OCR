import { FormEvent, useState } from "react"
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  ChevronDown,
  FileText,
  LogOut,
  Search,
  Settings,
} from "lucide-react"

import { api } from "@/api/client"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { CommandPalette } from "@/components/layout/CommandPalette"
import { ThemeToggle } from "@/components/layout/ThemeToggle"
import { useAuth } from "@/hooks/useAuth"
import { useWorkInboxCount } from "@/hooks/useWorkInboxCount"
import { cn } from "@/lib/utils"

const NAV_ITEMS = [
  { to: "/", label: "Inicio" },
  { to: "/documents", label: "Documentos" },
  { to: "/search", label: "Buscar" },
  { to: "/chat", label: "Chat IA" },
  { to: "/work-inbox", label: "Tareas", badge: true },
  { to: "/plans", label: "Planos", roles: ["admin", "gestor"] },
  { to: "/admin/sistema", label: "Admin", roles: ["admin"] },
]

export function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [query, setQuery] = useState("")

  const health = useQuery({ queryKey: ["system-health"], queryFn: api.systemHealth, refetchInterval: 30000, refetchIntervalInBackground: false })
  const inbox = useWorkInboxCount()
  const inboxCount = inbox.data?.count ?? 0
  const systemOk = health.data?.status === "ok" || health.data?.status === "ready"

  function onSearch(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (trimmed) navigate("/search?q=" + encodeURIComponent(trimmed))
    setQuery("")
  }

  const visibleNav = NAV_ITEMS.filter((item) => !item.roles || item.roles.includes(user?.role ?? ""))

  return (
    <div className="flex min-h-screen flex-col bg-[var(--bg-canvas)]">
      {/* ── Top Navigation Bar ── */}
      <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-[var(--bg-surface)] shadow-xs">
        <div className="flex h-12 items-center px-4 lg:px-6">
          {/* Brand */}
          <Link to="/" className="flex items-center gap-2.5 mr-6">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-[var(--accent)] text-white shadow-sm">
              <FileText className="h-3.5 w-3.5" />
            </div>
            <span className="text-[14px] font-bold text-[var(--text-primary)] hidden sm:block">Docu-Intel</span>
          </Link>

          {/* Nav links */}
          <nav className="hidden items-center gap-0.5 lg:flex">
            {visibleNav.map((item) => {
              const active = item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to)
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={cn(
                    "relative flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors",
                    active
                      ? "bg-[var(--accent-light)] text-[var(--accent)]"
                      : "text-[var(--text-secondary)] hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-primary)]",
                  )}
                >
                  {item.label}
                  {item.badge && inboxCount > 0 && (
                    <span className="ml-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-[var(--warning)] px-1 text-[9px] font-bold text-white">
                      {inboxCount > 99 ? "99+" : inboxCount}
                    </span>
                  )}
                </Link>
              )
            })}
          </nav>

          <div className="flex-1" />

          {/* Right side: search, status, theme, user */}
          <div className="flex items-center gap-2">
            <form className="relative hidden md:block" onSubmit={onSearch}>
              <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
              <Input
                className="h-8 w-48 rounded-md border-[var(--border)] bg-[var(--bg-surface-2)] pl-7 pr-8 text-[12px]"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar..."
              />
              <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-[var(--border)] bg-[var(--bg-surface)] px-1 font-mono text-[9px] text-[var(--text-muted)]">
                ⌘K
              </kbd>
            </form>

            <div className="hidden items-center gap-1 sm:flex">
              <span className={cn("h-1.5 w-1.5 rounded-full", systemOk ? "bg-[var(--success)]" : "bg-[var(--warning)]")} />
              <span className="text-[10px] text-[var(--text-muted)]">OK</span>
            </div>

            <ThemeToggle />

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="flex items-center gap-1.5 rounded-md px-2 py-1 hover:bg-[var(--bg-surface-2)]" aria-label="Usuario">
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--accent)] text-[11px] font-bold text-white">
                    {user?.name?.charAt(0)?.toUpperCase() ?? "U"}
                  </div>
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
          </div>
        </div>
      </header>

      {/* ── Content ── */}
      <main className="flex-1 p-4 lg:p-5">
        <Outlet />
      </main>

      <CommandPalette />
    </div>
  )
}
