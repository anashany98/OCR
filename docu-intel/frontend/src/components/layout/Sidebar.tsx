import { useState } from "react"
import { NavLink, useLocation } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  AlertCircle,
  BookOpen,
  Brain,
  Briefcase,
  ClipboardList,
  DatabaseZap,
  Eye,
  FileSearch,
  FileText,
  FileWarning,
  Filter,
  KeyRound,
  LayoutDashboard,
  Map,
  PanelLeftClose,
  PanelLeftOpen,
  Receipt,
  Scale,
  Search,
  Settings,
  Users,
} from "lucide-react"

import { api } from "@/api/client"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

type NavGroup = {
  id: string
  label: string
  items: NavItem[]
}

type NavItem = {
  to: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  badge?: boolean
  roles?: string[]
  beta?: boolean
}

export function Sidebar() {
  const { user } = useAuth()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const inbox = useQuery({
    queryKey: ["work-inbox-count"],
    queryFn: () => api.workInbox({ limit: 1 }),
    refetchInterval: 30000,
  })
  const inboxCount = inbox.data?.length ?? 0

  const navGroups: NavGroup[] = [
    {
      id: "inicio",
      label: "Inicio",
      items: [
        { to: "/", label: "Dashboard", icon: LayoutDashboard },
        { to: "/work-inbox", label: "Tareas", icon: AlertCircle, badge: true },
      ],
    },
    {
      id: "documentos",
      label: "Documentos",
      items: [
        { to: "/documents", label: "Todos los documentos", icon: FileText },
        { to: "/search", label: "Buscar", icon: Search },
        { to: "/chat", label: "Preguntar a documentos", icon: BookOpen },
        { to: "/plans", label: "Planos", icon: Map, roles: ["admin"], beta: true },
      ],
    },
    {
      id: "gestion",
      label: "Gestión",
      items: [
        { to: "/budgets", label: "Presupuestos", icon: Briefcase },
        { to: "/orders", label: "Pedidos", icon: ClipboardList },
        { to: "/invoices", label: "Facturas", icon: Receipt },
        { to: "/reconciliation", label: "Incidencias", icon: Scale },
      ],
    },
    {
      id: "revision",
      label: "Revisión",
      items: [
        { to: "/ocr-review", label: "OCR y calidad", icon: Eye },
        { to: "/admin?tab=calidad", label: "Duplicados", icon: FileWarning },
        { to: "/admin?tab=calidad", label: "Cuarentena", icon: Filter, roles: ["admin", "gestor"] },
      ],
    },
    {
      id: "tecnico",
      label: "Técnico",
      items: [
        { to: "/jobs", label: "Procesamiento", icon: DatabaseZap, roles: ["admin"] },
        { to: "/admin?tab=sistema", label: "Estado técnico", icon: Settings, roles: ["admin"] },
      ],
    },
    {
      id: "admin",
      label: "Administración",
      items: [
        { to: "/admin?tab=acceso", label: "Usuarios y permisos", icon: Users, roles: ["admin"] },
        { to: "/admin?tab=integraciones", label: "Integraciones", icon: KeyRound, roles: ["admin"] },
        { to: "/admin?tab=aprendizaje", label: "Aprendizaje IA", icon: Brain, roles: ["admin"] },
      ],
    },
  ]

  function canSeeItem(item: NavItem): boolean {
    if (!item.roles?.length) return true
    return user ? item.roles.includes(user.role) : false
  }

  function isActive(to: string): boolean {
    if (to === "/") return location.pathname === "/"
    return location.pathname.startsWith(to)
  }

  return (
    <aside
      className={cn(
        "flex flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar-bg)] transition-all duration-250 ease-out",
        collapsed ? "w-[56px]" : "w-[220px]",
      )}
    >
      {/* Logo */}
      <div className={cn("flex h-12 items-center border-b border-[var(--sidebar-border)] px-3", collapsed ? "justify-center" : "gap-2.5")}>
        <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md bg-[var(--primary)] text-white shadow-sm">
          <FileSearch className="h-3.5 w-3.5" />
        </div>
        {!collapsed && (
          <span className="text-[13px] font-semibold text-[var(--sidebar-text)] tracking-tight">Docu-Intel</span>
        )}
      </div>

      {/* Navigation groups */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden py-2">
        {navGroups.map((group) => {
          const visibleItems = group.items.filter(canSeeItem)
          if (!visibleItems.length) return null

          return (
            <div key={group.id} className="mb-3">
              {!collapsed && (
                <p className="px-3 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--sidebar-muted)]">
                  {group.label}
                </p>
              )}
              <div className="space-y-0.5 px-1.5">
                {visibleItems.map((item) => (
                  <NavLink
                    key={`${item.to}-${item.label}`}
                    to={item.to}
                    end={item.to === "/"}
                    title={collapsed ? item.label : undefined}
                    className={({ isActive: active }) =>
                      cn(
                        "group flex items-center rounded-md px-2 py-1.5 text-[12px] font-medium transition-colors duration-150",
                        collapsed ? "justify-center h-8 w-8 mx-auto" : "gap-2.5",
                        active
                          ? "bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)]"
                          : "text-[var(--sidebar-muted)] hover:bg-[var(--sidebar-active-bg)] hover:text-[var(--sidebar-text)]",
                      )
                    }
                  >
                    <item.icon className={cn("h-4 w-4 flex-shrink-0", collapsed && "h-4.5 w-4.5")} />
                    {!collapsed && (
                      <>
                        <span className="flex-1 truncate">{item.label}</span>
                        {item.badge && inboxCount > 0 && (
                          <span className="flex h-4.5 min-w-[18px] items-center justify-center rounded-full bg-[var(--primary)] px-1.5 text-[10px] font-semibold text-white leading-none">
                            {inboxCount > 99 ? "99+" : inboxCount}
                          </span>
                        )}
                        {item.beta && (
                          <span className="rounded bg-[var(--amber-light)] px-1.5 py-0.5 text-[9px] font-semibold uppercase text-[var(--amber)]">
                            Beta
                          </span>
                        )}
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          )
        })}
      </nav>

      {/* Collapse toggle */}
      <div className="border-t border-[var(--sidebar-border)] p-2">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex w-full items-center justify-center rounded-md py-1.5 text-[var(--sidebar-muted)] transition-colors hover:bg-[var(--sidebar-active-bg)] hover:text-[var(--sidebar-text)]"
          title={collapsed ? "Expandir menú" : "Colapsar menú"}
        >
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </button>
      </div>
    </aside>
  )
}
