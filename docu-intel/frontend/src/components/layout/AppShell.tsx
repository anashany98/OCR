import { FormEvent, useState } from "react"
import { Outlet, useLocation, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { CheckCircle2, ChevronDown, LogOut, Menu, Search, X } from "lucide-react"

import { api } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"
import { Sidebar } from "./Sidebar"

export function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [query, setQuery] = useState("")
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const health = useQuery({ queryKey: ["system-health"], queryFn: api.systemHealth, refetchInterval: 30000 })
  const inbox = useQuery({ queryKey: ["work-inbox-count"], queryFn: () => api.workInbox({ limit: 1 }), refetchInterval: 30000 })

  const inboxCount = inbox.data?.length ?? 0
  const currentPath = location.pathname

  const pageTitle = getPageTitle(currentPath)

  function onSearch(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (trimmed) navigate("/search?q=" + encodeURIComponent(trimmed))
    setQuery("")
  }

  const systemStatus = health.data?.status === "ok" || health.data?.status === "ready"

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg-base)]">
      {/* Sidebar - hidden on mobile */}
      <div className="hidden lg:block">
        <Sidebar />
      </div>

      {/* Mobile sidebar overlay */}
      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setMobileMenuOpen(false)} />
          <div className="absolute left-0 top-0 h-full">
            <Sidebar />
          </div>
        </div>
      )}

      {/* Main area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Topbar */}
        <header className="sticky top-0 z-20 border-b border-[var(--border)] bg-white/95 backdrop-blur-sm">
          <div className="flex h-12 items-center gap-3 px-4">
            {/* Mobile menu button */}
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="flex h-8 w-8 items-center justify-center rounded-md lg:hidden"
            >
              {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>

            {/* Page title */}
            <h1 className="hidden text-[14px] font-semibold text-[var(--text-primary)] sm:block">
              {pageTitle}
            </h1>

            {/* Spacer */}
            <div className="flex-1" />

            {/* Tareas badge */}
            {inboxCount > 0 && (
              <Badge variant="warning" className="hidden cursor-pointer items-center gap-1 sm:inline-flex" onClick={() => navigate("/work-inbox")}>
                <span>{inboxCount} {inboxCount === 1 ? "tarea" : "tareas"}</span>
              </Badge>
            )}

            {/* Search */}
            <form className="relative hidden sm:block" onSubmit={onSearch}>
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
              <Input
                className="h-8 w-48 rounded-md border-[var(--border)] bg-[var(--bg-surface-2)] pl-8 pr-3 text-[13px] placeholder:text-[var(--text-muted)] focus:border-[var(--primary)] focus:bg-white"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar documentos..."
              />
            </form>

            {/* Status indicator */}
            <div className="hidden items-center gap-1.5 sm:flex">
              <span className={cn("h-1.5 w-1.5 rounded-full", systemStatus ? "bg-[var(--emerald)]" : "bg-[var(--amber)]")} />
              <span className="text-[11px] text-[var(--text-muted)]">Sistema</span>
            </div>

            {/* User menu */}
            <div className="relative">
              <button className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[13px] transition-colors hover:bg-[var(--bg-surface-2)]">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--primary-light)] text-[var(--primary)] text-[11px] font-semibold">
                  {user?.name?.charAt(0)?.toUpperCase() ?? "U"}
                </div>
                <span className="hidden text-[var(--text-secondary)] sm:inline">{user?.name?.split(" ")[0]}</span>
                <ChevronDown className="hidden h-3 w-3 text-[var(--text-muted)] sm:block" />
              </button>
            </div>

            {/* Logout */}
            <Button variant="ghost" size="icon" onClick={logout} className="h-8 w-8 text-[var(--text-muted)] hover:text-[var(--rose)]" title="Cerrar sesión">
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        </header>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto px-4 py-5 lg:px-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function getPageTitle(pathname: string): string {
  const titles: Record<string, string> = {
    "/": "Dashboard",
    "/documents": "Documentos",
    "/work-inbox": "Tareas",
    "/ocr-review": "Revisión OCR",
    "/search": "Buscar",
    "/chat": "Preguntar a documentos",
    "/jobs": "Procesamiento",
    "/budgets": "Presupuestos",
    "/orders": "Pedidos",
    "/invoices": "Facturas",
    "/reconciliation": "Incidencias",
    "/plans": "Planos",
    "/admin": "Administración",
  }

  if (titles[pathname]) return titles[pathname]
  if (pathname.startsWith("/documents/")) return "Detalle de documento"
  return "Docu-Intel"
}
