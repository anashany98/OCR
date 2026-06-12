import { useEffect, useMemo, useState } from "react"
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
  Map as MapIcon,
  Receipt,
  Scale,
  Search,
  Settings,
  Users,
} from "lucide-react"

import { api } from "@/api/client"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"
import { ADMIN_TAB_LABELS } from "@/routes/adminTabs"

export type NavItem = {
  to: string
  label: string
  icon: React.ComponentType<{ className?: string }>
  badge?: boolean
  roles?: string[]
  beta?: boolean
  keywords?: string[]
}

export type NavGroup = {
  id: string
  label: string
  description?: string
  items: NavItem[]
}

// ---------------------------------------------------------------------------
// Navigation config. Ordered by user workflow:
//   1. General      — entry points (start of session)
//   2. Documentos   — primary data surface (read / search)
//   3. Operación    — business workflow (budgets → orders → invoices)
//   4. Sistema      — admin / technical (only when needed)
// ---------------------------------------------------------------------------
export const NAV_GROUPS: NavGroup[] = [
  {
    id: "general",
    label: "General",
    items: [
      {
        to: "/",
        label: "Dashboard",
        icon: LayoutDashboard,
        keywords: ["resumen", "inicio", "panel"],
      },
      {
        to: "/work-inbox",
        label: "Tareas",
        icon: AlertCircle,
        badge: true,
        keywords: ["incidencias", "cola"],
      },
    ],
  },
  {
    id: "documentos",
    label: "Documentos",
    items: [
      {
        to: "/documents",
        label: "Todos los documentos",
        icon: FileText,
        keywords: ["listado", "tabla"],
      },
      { to: "/search", label: "Buscar", icon: Search, keywords: ["encontrar", "consulta"] },
      {
        to: "/chat",
        label: "Preguntar a documentos",
        icon: BookOpen,
        keywords: ["ia", "rag", "chat"],
      },
      {
        to: "/plans",
        label: "Planos",
        icon: MapIcon,
        roles: ["admin", "gestor"],
        beta: true,
        keywords: ["dwg", "cad"],
      },
    ],
  },
  {
    id: "operacion",
    label: "Operación",
    items: [
      { to: "/budgets", label: "Presupuestos", icon: Briefcase, keywords: ["oferta"] },
      { to: "/orders", label: "Pedidos", icon: ClipboardList, keywords: ["orden"] },
      { to: "/invoices", label: "Facturas", icon: Receipt, keywords: ["cobro"] },
      {
        to: "/reconciliation",
        label: "Incidencias",
        icon: Scale,
        keywords: ["conciliación", "diferencias"],
      },
      {
        to: "/ocr-review",
        label: "OCR y calidad",
        icon: Eye,
        keywords: ["revisión", "baja confianza"],
      },
      { to: "/admin/calidad", label: "Duplicados", icon: FileWarning, keywords: ["duplicado"] },
      {
        to: "/admin/calidad",
        label: "Cuarentena",
        icon: Filter,
        roles: ["admin", "gestor"],
        keywords: ["cuarentena", "seguridad"],
      },
    ],
  },
  {
    id: "sistema",
    label: "Sistema",
    items: [
      {
        to: "/jobs",
        label: "Procesamiento",
        icon: DatabaseZap,
        roles: ["admin"],
        keywords: ["jobs", "celery", "cola"],
      },
      {
        to: "/admin/sistema",
        label: ADMIN_TAB_LABELS.sistema,
        icon: Settings,
        roles: ["admin"],
        keywords: ["salud", "infraestructura"],
      },
      {
        to: "/admin/acceso",
        label: ADMIN_TAB_LABELS.acceso,
        icon: Users,
        roles: ["admin"],
        keywords: ["permisos", "rbac"],
      },
      {
        to: "/admin/integraciones",
        label: ADMIN_TAB_LABELS.integraciones,
        icon: KeyRound,
        roles: ["admin"],
        keywords: ["api", "cliente", "webhook"],
      },
      {
        to: "/admin/aprendizaje",
        label: ADMIN_TAB_LABELS.aprendizaje,
        icon: Brain,
        roles: ["admin"],
        keywords: ["ia", "patrones"],
      },
    ],
  },
]

const RECENT_KEY_PREFIX = "docu-intel:recent-nav:"

function readRecent(userId: string | number | undefined): string[] {
  if (typeof window === "undefined" || !userId) return []
  try {
    const raw = window.localStorage.getItem(RECENT_KEY_PREFIX + userId)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === "string").slice(0, 4)
      : []
  } catch {
    return []
  }
}

function writeRecent(userId: string | number | undefined, paths: string[]) {
  if (typeof window === "undefined" || !userId) return
  try {
    window.localStorage.setItem(RECENT_KEY_PREFIX + userId, JSON.stringify(paths.slice(0, 4)))
  } catch {
    /* ignore quota errors */
  }
}

// ---------------------------------------------------------------------------
// SidebarNav — shared navigation content used by the persistent desktop
// sidebar and the mobile drawer.
// ---------------------------------------------------------------------------
export function SidebarNav({
  embedded = false,
  onNavigate,
}: {
  embedded?: boolean
  onNavigate?: () => void
}) {
  const { user } = useAuth()
  const location = useLocation()
  const [recentPaths, setRecentPaths] = useState<string[]>(() => readRecent(user?.id))

  useEffect(() => {
    if (!user) return
    const segments = location.pathname.split("/").filter(Boolean)
    const currentPath = segments.length ? "/" + segments[0] : "/"
    if (!currentPath || currentPath === "/") return
    setRecentPaths((prev) => {
      const next = [currentPath, ...prev.filter((p) => p !== currentPath)].slice(0, 4)
      writeRecent(user.id, next)
      return next
    })
  }, [location.pathname, user])

  const inbox = useQuery({
    queryKey: ["work-inbox-count"],
    queryFn: () => api.workInboxCount(),
    refetchInterval: 30000,
  })
  const inboxCount = inbox.data?.count ?? 0

  const allItems = useMemo(() => {
    const map = new Map<string, NavItem>()
    for (const group of NAV_GROUPS) {
      for (const item of group.items) {
        const basePath = item.to.split("?")[0]
        if (!map.has(basePath)) map.set(basePath, item)
      }
    }
    return map
  }, [])

  const recentItems = useMemo(() => {
    return recentPaths
      .map((p) => allItems.get(p))
      .filter((item): item is NavItem => Boolean(item))
      .filter((item) => canSee(item, user?.role))
  }, [recentPaths, allItems, user])

  function canSee(item: NavItem, role: string | undefined): boolean {
    if (!item.roles?.length) return true
    return role ? item.roles.includes(role) : false
  }

  function isActive(to: string): boolean {
    const [path, hash] = to.split("?")[0].split("#")
    const targetHash = to.includes("#") ? to.split("#")[1] : undefined
    if (path === "/") return location.pathname === "/" && !location.hash
    if (location.pathname !== path) return false
    if (targetHash && location.hash !== `#${targetHash}`) return false
    return true
  }

  const groupSpacing = embedded ? "mb-5 last:mb-3" : "mb-5 last:mb-3"

  return (
    <div className={cn("flex flex-col h-full", embedded ? "p-3" : "py-3")}>
      {/* Recientes */}
      {recentItems.length > 0 && (
        <div className={cn("mb-4", !embedded && "border-b border-[var(--sidebar-border)]/50 pb-3")}>
          <SidebarSectionLabel>Recientes</SidebarSectionLabel>
          <ul className="space-y-0.5">
            {recentItems.map((item) => {
              const Icon = item.icon
              const active = isActive(item.to)
              return (
                <li key={`recent-${item.to}`}>
                  <NavLink
                    to={item.to}
                    onClick={() => onNavigate?.()}
                    className={cn(
                      "group/item flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[12.5px] transition-colors duration-fast ease-out",
                      active
                        ? "bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)]"
                        : "text-[var(--sidebar-muted)] hover:bg-[var(--sidebar-active-bg)]/60 hover:text-[var(--sidebar-text)]",
                    )}
                    title={item.label}
                  >
                    <Icon className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
                    <span className="truncate">{item.label}</span>
                  </NavLink>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      {/* Nav groups */}
      {NAV_GROUPS.map((group) => {
        const visibleItems = group.items.filter((item) => canSee(item, user?.role))
        if (!visibleItems.length) return null
        return (
          <div
            key={group.id}
            className={cn(
              groupSpacing,
              !embedded &&
                "border-t border-[var(--sidebar-border)]/50 pt-3 first:border-t-0 first:pt-0",
            )}
          >
            <SidebarSectionLabel>{group.label}</SidebarSectionLabel>
            <ul className="space-y-0.5">
              {visibleItems.map((item) => (
                <SidebarItem
                  key={`${item.to}-${item.label}`}
                  item={item}
                  active={isActive(item.to)}
                  inboxCount={item.badge ? inboxCount : 0}
                  onNavigate={onNavigate}
                />
              ))}
            </ul>
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section label
// ---------------------------------------------------------------------------
function SidebarSectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-1.5 flex items-center gap-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--sidebar-muted)]">
      <span className="h-px w-2 bg-[var(--sidebar-muted)]/40" aria-hidden="true" />
      <span>{children}</span>
    </p>
  )
}

// ---------------------------------------------------------------------------
// SidebarItem — active state with terracotta accent bar
// ---------------------------------------------------------------------------
function SidebarItem({
  item,
  active,
  inboxCount,
  onNavigate,
}: {
  item: NavItem
  active: boolean
  inboxCount: number
  onNavigate?: () => void
}) {
  const Icon = item.icon
  return (
    <li>
      <NavLink
        to={item.to}
        end={item.to === "/"}
        aria-current={active ? "page" : undefined}
        onClick={() => onNavigate?.()}
        className={cn(
          "group/item relative flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[12.5px] font-medium tracking-tight transition-all duration-fast ease-out",
          active
            ? "bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)]"
            : "text-[var(--sidebar-muted)] hover:bg-[var(--sidebar-active-bg)]/50 hover:text-[var(--sidebar-text)]",
        )}
      >
        {active && (
          <span
            aria-hidden="true"
            className="absolute inset-y-1.5 left-0 w-0.5 rounded-r-full bg-[var(--accent)]"
          />
        )}
        <Icon
          className={cn(
            "h-4 w-4 flex-shrink-0 transition-transform duration-fast ease-out",
            active && "scale-105",
          )}
          aria-hidden="true"
        />
        <span className="flex-1 truncate">{item.label}</span>
        {item.badge && inboxCount > 0 && (
          <span
            aria-label={`${inboxCount} ${inboxCount === 1 ? "tarea pendiente" : "tareas pendientes"}`}
            className={cn(
              "flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1.5 text-[10px] font-semibold tabular-nums leading-none",
              active
                ? "bg-[var(--accent)] text-white"
                : "bg-[var(--sidebar-muted)]/25 text-[var(--sidebar-text)]",
            )}
          >
            {inboxCount > 99 ? "99+" : inboxCount}
          </span>
        )}
        {item.beta && (
          <span className="rounded border border-[var(--warning)]/30 bg-[var(--warning-faint)] px-1 py-px text-[8.5px] font-semibold uppercase tracking-[0.08em] text-[var(--text-on-warning)]">
            β
          </span>
        )}
      </NavLink>
    </li>
  )
}
