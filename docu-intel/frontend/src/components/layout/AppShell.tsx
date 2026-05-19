import { FormEvent, useMemo, useState } from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  AlertCircle,
  Bot,
  Briefcase,
  CheckCircle2,
  ChevronDown,
  ClipboardList,
  CircleGauge,
  Eye,
  FileSearch,
  FileText,
  Home,
  Inbox,
  LayoutDashboard,
  LogOut,
  Map,
  Menu,
  Scale,
  Search,
  Settings,
  UploadCloud,
  X,
} from "lucide-react"

import { api } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

const navItems = [
  { to: "/", label: "Hoy", icon: Home },
  { to: "/documents", label: "Documentos", icon: FileText },
  { to: "/work-inbox", label: "Bandeja", icon: Inbox, badge: true },
  { to: "/ocr-review", label: "Revisión OCR", icon: Eye },
  { to: "/search", label: "Búsqueda", icon: Search },
  { to: "/chat", label: "Chat IA", icon: Bot },
  { to: "/budgets", label: "Presupuestos", icon: Briefcase },
  { to: "/orders", label: "Pedidos", icon: ClipboardList },
  { to: "/plans", label: "Planos", icon: Map },
  { to: "/reconciliation", label: "Conciliación", icon: Scale },
  { to: "/jobs", label: "Jobs", icon: CircleGauge },
  { to: "/admin", label: "Admin", icon: Settings },
]

export function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [query, setQuery] = useState("")
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const health = useQuery({ queryKey: ["system-health"], queryFn: api.systemHealth, refetchInterval: 30000 })
  const inbox = useQuery({ queryKey: ["work-inbox-count"], queryFn: () => api.workInbox({ limit: 1 }), refetchInterval: 30000 })

  const inboxCount = inbox.data?.length ?? 0
  const currentPage = useMemo(() => {
    const item = navItems.find((n) =>
      n.to === "/" ? location.pathname === "/" : location.pathname.startsWith(n.to)
    )
    return item?.label ?? "Docu-Intel"
  }, [location.pathname])

  function onSearch(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (trimmed) navigate("/search?q=" + encodeURIComponent(trimmed))
    setQuery("")
  }

  const systemStatus = health.data?.status === "ok" || health.data?.status === "ready"

  return (
    <div className="min-h-screen bg-[var(--bg-base)]">
      {/* Topbar */}
      <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-white/95 backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-screen-xl items-center gap-4 px-4 lg:px-6">
          {/* Logo */}
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--primary)] text-white shadow-sm">
              <FileSearch className="h-4 w-4" />
            </div>
            <span className="hidden text-[15px] font-semibold text-[var(--text-primary)] sm:block">Docu-Intel</span>
          </div>

          {/* Navigation - desktop */}
          <nav className="hidden items-center gap-1 lg:flex">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "relative flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium transition-colors duration-150",
                    "text-[var(--text-secondary)] hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-primary)]",
                    isActive && "text-[var(--primary)]"
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    <item.icon className="h-4 w-4" />
                    {item.label}
                    {item.badge && inboxCount > 0 && (
                      <span className="ml-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-[var(--primary)] px-1 text-[10px] font-semibold text-white">
                        {inboxCount}
                      </span>
                    )}
                    {isActive && (
                      <span className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full bg-[var(--primary)]" />
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </nav>

          {/* Spacer */}
          <div className="flex-1" />

          {/* Search */}
          <form className="relative hidden sm:block" onSubmit={onSearch}>
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
            <Input
              className="h-8 w-48 rounded-md border-[var(--border)] bg-[var(--bg-surface-2)] pl-8 pr-16 text-[13px] placeholder:text-[var(--text-muted)] focus:border-[var(--primary)] focus:bg-white"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar documentos..."
            />
            <kbd className="absolute right-2 top-1/2 -translate-y-1/2 rounded border border-[var(--border)] bg-white px-1 py-0.5 text-[10px] text-[var(--text-muted)]">
              ⌘K
            </kbd>
          </form>

          {/* Status indicators */}
          <div className="hidden items-center gap-2 sm:flex">
            <div className="flex items-center gap-1.5">
              <span className={cn("h-1.5 w-1.5 rounded-full", systemStatus ? "bg-[var(--emerald)]" : "bg-[var(--amber)]")} />
              <span className="text-[12px] text-[var(--text-muted)]">Sistema</span>
            </div>
          </div>

          {/* User menu */}
          <div className="relative hidden sm:block">
            <button className="flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] transition-colors hover:bg-[var(--bg-surface-2)]">
              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[var(--primary-light)] text-[var(--primary)] text-[12px] font-semibold">
                {user?.name?.charAt(0)?.toUpperCase() ?? "U"}
              </div>
              <span className="text-[var(--text-secondary)]">{user?.name?.split(" ")[0]}</span>
              <ChevronDown className="h-3 w-3 text-[var(--text-muted)]" />
            </button>
          </div>

          {/* Mobile menu button */}
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="flex h-8 w-8 items-center justify-center rounded-md lg:hidden"
          >
            {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>

        {/* Mobile navigation */}
        {mobileMenuOpen && (
          <nav className="border-t border-[var(--border)] bg-white px-4 py-3 lg:hidden">
            <div className="flex flex-col gap-1">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  onClick={() => setMobileMenuOpen(false)}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
                      isActive
                        ? "bg-[var(--primary-light)] text-[var(--primary)]"
                        : "text-[var(--text-secondary)] hover:bg-[var(--bg-surface-2)]"
                    )
                  }
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                  {item.badge && inboxCount > 0 && (
                    <span className="ml-auto flex h-5 min-w-[20px] items-center justify-center rounded-full bg-[var(--primary)] px-1.5 text-[11px] font-semibold text-white">
                      {inboxCount}
                    </span>
                  )}
                </NavLink>
              ))}
            </div>
            <div className="mt-3 flex items-center justify-between border-t border-[var(--border)] pt-3">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--primary-light)] text-[var(--primary)] text-[12px] font-semibold">
                  {user?.name?.charAt(0)?.toUpperCase() ?? "U"}
                </div>
                <div>
                  <p className="text-[13px] font-medium">{user?.name}</p>
                  <p className="text-[11px] text-[var(--text-muted)]">{user?.email}</p>
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={logout} className="text-[var(--rose)]">
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
          </nav>
        )}
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-screen-xl px-4 py-6 lg:px-6">
        {/* Page title bar */}
        <div className="mb-6 flex items-center justify-between">
          <div className="animate-fade-in-up">
            <h1 className="text-xl font-semibold text-[var(--text-primary)]">{currentPage}</h1>
            <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
              {new Date().toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" })}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* Quick status */}
            <div className="hidden items-center gap-2 rounded-md border border-[var(--border)] bg-white px-3 py-1.5 sm:flex">
              <CheckCircle2 className="h-3.5 w-3.5 text-[var(--emerald)]" />
              <span className="text-[12px] text-[var(--text-secondary)]">Cola estable</span>
            </div>
          </div>
        </div>

        <Outlet />
      </main>
    </div>
  )
}