/**
 * Single source of truth for navigation data and page titles.
 *
 * Before this module existed, the same data was spread across three
 * places that had to be kept in sync by hand:
 *
 *   1. ``components/layout/Sidebar.tsx`` exported its own
 *      ``NAV_GROUPS`` with hardcoded labels.
 *   2. ``components/layout/navigation.ts`` exported a parallel
 *      ``NAV_GROUPS`` plus ``NAV_ROUTE_TITLES`` that nobody read.
 *   3. ``routes/router.tsx`` set ``handle.title`` on every route.
 *
 * Consumers (sidebar, command palette, app shell page title reader,
 * router) all import from here. When a route or label changes, edit
 * this file and the test in ``config.test.ts`` will catch missing
 * entries.
 */
import type { ComponentType } from "react"
import {
  AlertCircle,
  BookOpen,
  Brain,
  Briefcase,
  ClipboardList,
  DatabaseZap,
  Eye,
  FileText,
  FileWarning,
  Filter,
  KeyRound,
  LayoutDashboard,
  Map as MapIcon,
  Receipt,
  Scale,
  ScanSearch,
  Search,
  Settings,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type NavItem = {
  /** Destination path. Use ``:id`` for params. */
  to: string
  /** Display label in the sidebar / palette. */
  label: string
  icon: ComponentType<{ className?: string }>
  /** Show the live "tareas pendientes" badge here. */
  badge?: boolean
  /** Hide the item unless the user role is in this list. */
  roles?: readonly string[]
  /** Mark the item as a beta feature. */
  beta?: boolean
  /** Extra keywords for the command palette fuzzy search. */
  keywords?: readonly string[]
}

export type NavGroup = {
  id: string
  label: string
  items: readonly NavItem[]
}

// ---------------------------------------------------------------------------
// Menu configuration
// ---------------------------------------------------------------------------

/**
 * Top-level menu groups. Ordered by user workflow:
 *   1. General     — entry points
 *   2. Documentos  — primary data surface
 *   3. Operación   — business workflow
 *   4. Sistema     — admin / technical
 */
export const NAV_GROUPS: readonly NavGroup[] = [
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
      {
        to: "/search",
        label: "Buscar",
        icon: Search,
        keywords: ["encontrar", "consulta"],
      },
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
      {
        to: "/admin/calidad",
        label: "Duplicados",
        icon: FileWarning,
        keywords: ["duplicado"],
      },
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
        label: "Estado técnico",
        icon: Settings,
        roles: ["admin"],
        keywords: ["salud", "infraestructura"],
      },
      {
        to: "/admin/acceso",
        label: "Usuarios y permisos",
        icon: Users,
        roles: ["admin"],
        keywords: ["permisos", "rbac"],
      },
      {
        to: "/admin/integraciones",
        label: "Integraciones",
        icon: KeyRound,
        roles: ["admin"],
        keywords: ["api", "cliente", "webhook"],
      },
      {
        to: "/admin/aprendizaje",
        label: "Aprendizaje IA",
        icon: Brain,
        roles: ["admin"],
        keywords: ["ia", "patrones"],
      },
    ],
  },
] as const

/** Flat lookup by path. The first item with a given path wins. */
export const NAV_ITEMS_BY_PATH: ReadonlyMap<string, NavItem> = (() => {
  const map = new Map<string, NavItem>()
  for (const group of NAV_GROUPS) {
    for (const item of group.items) {
      const basePath = item.to.split("?")[0]
      if (!map.has(basePath)) map.set(basePath, item)
    }
  }
  return map
})()

// ---------------------------------------------------------------------------
// Page titles (used by AppShell.getPageTitle as the canonical source)
// ---------------------------------------------------------------------------

/**
 * Canonical title for every user-facing path. Path syntax is the
 * same as React Router (``:id`` for params, ``*`` for catch-all).
 *
 * The router no longer sets ``handle.title``; this map is the
 * single source. :func:`titleForPath` resolves a runtime pathname
 * against it.
 */
export const NAV_ROUTE_TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/documents": "Documentos",
  "/documents/:id": "Detalle de documento",
  "/documents/:id/annotate-plan": "Anotar plano",
  "/work-inbox": "Tareas",
  "/ocr-review": "Revisión OCR",
  "/search": "Buscar",
  "/jobs": "Procesamiento",
  "/budgets": "Presupuestos",
  "/orders": "Pedidos",
  "/invoices": "Facturas",
  "/reconciliation": "Incidencias",
  "/plans": "Planos",
  "/chat": "Preguntar a documentos",
  "/admin": "Administración",
  "/admin/operativa": "Administración · Operativa",
  "/admin/sistema": "Administración · Estado técnico",
  "/admin/integraciones": "Administración · Integraciones",
  "/admin/acceso": "Administración · Usuarios y permisos",
  "/admin/calidad": "Administración · Calidad",
  "/admin/aprendizaje": "Administración · Aprendizaje IA",
  "*": "No encontrado",
}

/**
 * Resolve a runtime pathname to its canonical title.
 *
 * Exact matches win; otherwise the registered pattern with the
 * same segment count after normalising ``:param`` segments wins.
 * Returns ``"Docu-Intel"`` when no pattern matches.
 */
export function titleForPath(pathname: string): string {
  if (NAV_ROUTE_TITLES[pathname]) {
    return NAV_ROUTE_TITLES[pathname]
  }
  const segments = pathname.split("/").filter(Boolean)
  let bestMatch = ""
  for (const pattern of Object.keys(NAV_ROUTE_TITLES)) {
    if (pattern === "*") continue
    const patternSegments = pattern.split("/").filter(Boolean)
    if (patternSegments.length !== segments.length) continue
    let compatible = true
    for (let i = 0; i < patternSegments.length; i++) {
      const ps = patternSegments[i]
      const ss = segments[i]
      if (ps.startsWith(":")) continue
      if (ps !== ss) {
        compatible = false
        break
      }
    }
    if (compatible && pattern.length > bestMatch.length) {
      bestMatch = pattern
    }
  }
  return (bestMatch && NAV_ROUTE_TITLES[bestMatch]) || "Docu-Intel"
}

// ---------------------------------------------------------------------------
// Role visibility
// ---------------------------------------------------------------------------

export function canSeeNavItem(item: NavItem, role: string | undefined): boolean {
  if (!item.roles?.length) return true
  return role ? item.roles.includes(role) : false
}

// ---------------------------------------------------------------------------
// Admin tabs (consumed by the admin shell + the /admin router tree)
// ---------------------------------------------------------------------------

export type AdminTab =
  | "operativa"
  | "sistema"
  | "integraciones"
  | "acceso"
  | "calidad"
  | "aprendizaje"

export const ADMIN_TABS: ReadonlyArray<{
  id: AdminTab
  label: string
  icon: LucideIcon
}> = [
  { id: "operativa", label: "Operativa", icon: ShieldCheck },
  { id: "sistema", label: "Estado técnico", icon: Settings },
  { id: "integraciones", label: "Integraciones", icon: KeyRound },
  { id: "acceso", label: "Usuarios y permisos", icon: Users },
  { id: "calidad", label: "Calidad", icon: ScanSearch },
  { id: "aprendizaje", label: "Aprendizaje IA", icon: Brain },
] as const

export const ADMIN_TAB_IDS: ReadonlySet<AdminTab> = new Set(ADMIN_TABS.map((t) => t.id))

/** Coerce an arbitrary string (e.g. URL param) to a known admin tab. */
export function normalizeAdminTab(value: string | null | undefined): AdminTab {
  return value && ADMIN_TAB_IDS.has(value as AdminTab) ? (value as AdminTab) : "operativa"
}
