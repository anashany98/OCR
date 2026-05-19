import { FormEvent, useMemo, useState } from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  AlertTriangle,
  Bot,
  BriefcaseBusiness,
  ClipboardList,
  Inbox,
  FileSearch,
  Files,
  Gauge,
  Eye,
  LayoutDashboard,
  LogOut,
  Map,
  Search,
  Settings,
  Scale,
  UploadCloud,
} from "lucide-react"

import { api } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

const navGroups = [
  {
    label: "Operación",
    items: [
      { to: "/", label: "Hoy", icon: LayoutDashboard },
      { to: "/work-inbox", label: "Bandeja", icon: Inbox },
      { to: "/documents", label: "Documentos", icon: Files },
      { to: "/ocr-review", label: "Revisión OCR", icon: Eye },
    ],
  },
  {
    label: "Inteligencia",
    items: [
      { to: "/search", label: "Búsqueda", icon: FileSearch },
      { to: "/chat", label: "Chat IA", icon: Bot },
    ],
  },
  {
    label: "Negocio",
    items: [
      { to: "/budgets", label: "Presupuestos", icon: BriefcaseBusiness },
      { to: "/orders", label: "Pedidos", icon: ClipboardList },
      { to: "/reconciliation", label: "Conciliación", icon: Scale },
      { to: "/plans", label: "Planos", icon: Map },
    ],
  },
  {
    label: "Sistema",
    items: [
      { to: "/jobs", label: "Jobs", icon: Gauge },
      { to: "/admin", label: "Administración", icon: Settings },
    ],
  },
]

export function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [query, setQuery] = useState("")
  const health = useQuery({ queryKey: ["system-health", "shell"], queryFn: api.systemHealth, refetchInterval: 30000 })
  const queues = useQuery({ queryKey: ["queues", "shell"], queryFn: api.queues, refetchInterval: 30000 })

  const currentTitle = useMemo(() => {
    const item = navGroups
      .flatMap((group) => group.items)
      .sort((left, right) => right.to.length - left.to.length)
      .find((candidate) => location.pathname === candidate.to || (candidate.to !== "/" && location.pathname.startsWith(candidate.to + "/")))
    return item?.label ?? "Docu-Intel"
  }, [location.pathname])

  function onSearch(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (trimmed) navigate("/search?q=" + encodeURIComponent(trimmed))
  }

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 hidden border-r bg-slate-950 text-slate-100 md:flex md:w-64 md:flex-col">
        <div className="flex h-16 items-center gap-3 border-b border-white/10 px-4">
          <div className="flex size-9 items-center justify-center rounded-md bg-cyan-500 text-white">
            <UploadCloud data-icon="inline-start" />
          </div>
          <div>
            <p className="text-sm font-semibold leading-none">Docu-Intel</p>
            <p className="text-xs text-slate-400">Operación documental</p>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-4 overflow-y-auto p-3">
          {navGroups.map((group) => (
            <div key={group.label}>
              <p className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-normal text-slate-500">{group.label}</p>
              <div className="flex flex-col gap-1">
                {group.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) =>
                      cn(
                        "flex h-9 items-center gap-2 rounded-md px-3 text-sm text-slate-300 hover:bg-white/10 hover:text-white",
                        isActive && "bg-white text-slate-950 shadow-sm hover:bg-white hover:text-slate-950",
                      )
                    }
                  >
                    <item.icon data-icon="inline-start" />
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>
        <div className="border-t border-white/10 p-3">
          <p className="truncate text-sm font-medium text-white">{user?.name}</p>
          <p className="truncate text-xs text-slate-400">{user?.email}</p>
          <Button className="mt-3 w-full border-white/15 bg-transparent text-slate-100 hover:bg-white/10" variant="outline" size="sm" onClick={logout}>
            <LogOut data-icon="inline-start" />
            Salir
          </Button>
        </div>
      </aside>
      <main className="min-h-screen md:pl-64">
        <div className="sticky top-0 z-20 border-b bg-card/95 px-4 py-3 backdrop-blur md:px-6">
          <div className="mx-auto flex max-w-7xl flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="min-w-0">
              <p className="text-xs font-medium uppercase tracking-normal text-muted-foreground">Área actual</p>
              <h1 className="truncate text-base font-semibold text-slate-950">{currentTitle}</h1>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <form className="relative min-w-0 sm:w-80" onSubmit={onSearch}>
                <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input className="h-9 pl-8" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar documentos, referencias..." />
              </form>
              <Badge variant={health.data?.status === "ok" || health.data?.status === "ready" ? "success" : health.isError ? "danger" : "neutral"}>
                Sistema {health.data?.status ?? (health.isLoading ? "..." : "sin datos")}
              </Badge>
              <Badge variant={queues.data?.backpressure_active ? "warning" : "neutral"}>
                <AlertTriangle className="mr-1 h-3 w-3" />
                Cola {queues.data?.pending_jobs ?? "-"}
              </Badge>
            </div>
          </div>
        </div>
        <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
