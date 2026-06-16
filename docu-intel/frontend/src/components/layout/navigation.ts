/**
 * F7: single source of truth for navigation labels and page titles.
 *
 * Before this module the page title (read in `AppShell.getPageTitle`
 * from the route's `handle.title`) and the menu label (read from
 * `NAV_GROUPS` in `Sidebar.tsx`) were two independent string
 * constants that could drift apart when one was updated and the
 * other forgotten. This module exports a single `NAV_ROUTE_TITLES`
 * map keyed by the route path so:
 *
 * 1. The router can derive `handle.title` from the same string
 *    the menu uses.
 * 2. The `getPageTitle` reader in `AppShell` falls back to
 *    `NAV_ROUTE_TITLES` for any path that does not set an
 *    explicit title, so paths like `/documents/:id/annotate-plan`
 *    (previously falling through to "Docu-Intel") get a real label.
 *
 * Keep this file in sync with `routes/router.tsx` — when a new
 * page is added, add the entry here AND in the router. The CI
 * test `tests/navigation.test.ts` enforces the contract.
 */
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
  Search,
  Settings,
  Users,
} from "lucide-react"

import type { ComponentType } from "react"

/**
 * Canonical title for every user-facing path. The path pattern uses
 * the same syntax as React Router (``:id`` for params, ``*`` for
 * the catch-all).
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
 * Match a runtime pathname against the canonical route patterns
 * in :data:`NAV_ROUTE_TITLES`. Exact matches win; otherwise the
 * first pattern that matches a non-param segment count wins.
 *
 * Used by ``AppShell.getPageTitle`` as a fallback when the route
 * does not declare ``handle.title`` of its own.
 */
export function titleForPath(pathname: string): string {
  if (NAV_ROUTE_TITLES[pathname]) {
    return NAV_ROUTE_TITLES[pathname]
  }
  // Walk the registered patterns and pick the longest match that
  // shares the same segment count after normalising params.
  const segments = pathname.split("/").filter(Boolean)
  let best_match = ""
  for (const pattern of Object.keys(NAV_ROUTE_TITLES)) {
    if (pattern === "*") continue
    const pat_segments = pattern.split("/").filter(Boolean)
    if (pat_segments.length !== segments.length) continue
    let compatible = true
    for (let i = 0; i < pat_segments.length; i++) {
      const ps = pat_segments[i]
      const ss = segments[i]
      if (ps.startsWith(":")) continue
      if (ps !== ss) {
        compatible = false
        break
      }
    }
    if (compatible && pattern.length > best_match.length) {
      best_match = pattern
    }
  }
  return (best_match && NAV_ROUTE_TITLES[best_match]) || "Docu-Intel"
}

// ---------------------------------------------------------------------------
// Menu navigation (consumed by Sidebar and CommandPalette).
// ---------------------------------------------------------------------------

export type NavItem = {
  to: string
  /** Override the menu label; defaults to the canonical NAV_ROUTE_TITLES entry. */
  label?: string
  icon: ComponentType<{ className?: string }>
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

/** Same as NavGroup, but every item has its `label` resolved. */
export type ResolvedNavGroup = Omit<NavGroup, "items"> & {
  items: Array<NavItem & { label: string }>
}

const _DashboardIcon = LayoutDashboard
const _TasksIcon = AlertCircle
const _DocsIcon = FileText
const _SearchIcon = Search
const _ChatIcon = BookOpen
const _PlansIcon = MapIcon
const _BudgetsIcon = Briefcase
const _OrdersIcon = ClipboardList
const _InvoicesIcon = Receipt
const _ReconciliationIcon = Scale
const _OcrReviewIcon = Eye
const _DuplicatesIcon = FileWarning
const _QuarantineIcon = Filter
const _JobsIcon = DatabaseZap
const _AdminSystemIcon = Settings
const _AdminAccessIcon = Users
const _AdminIntegrationsIcon = KeyRound
const _AdminLearningIcon = Brain

/**
 * Ordered by user workflow. Each item pulls its label from
 * :data:`NAV_ROUTE_TITLES` (the single source of truth) unless the
 * entry explicitly overrides it. The `label` is then resolved at
 * module-load time by :func:`_resolveLabels` so consumers see a
 * fully-populated ``NavItem.label``.
 */
export const NAV_GROUPS_RAW: NavGroup[] = [
  {
    id: "general",
    label: "General",
    items: [
      { to: "/", icon: _DashboardIcon, keywords: ["resumen", "inicio", "panel"] },
      { to: "/work-inbox", icon: _TasksIcon, badge: true, keywords: ["incidencias", "cola"] },
    ],
  },
  {
    id: "documentos",
    label: "Documentos",
    items: [
      { to: "/documents", icon: _DocsIcon, keywords: ["listado", "tabla"] },
      { to: "/search", icon: _SearchIcon, keywords: ["encontrar", "consulta"] },
      { to: "/chat", icon: _ChatIcon, keywords: ["ia", "rag", "chat"] },
      { to: "/plans", icon: _PlansIcon, roles: ["admin", "gestor"], beta: true, keywords: ["dwg", "cad"] },
    ],
  },
  {
    id: "operacion",
    label: "Operación",
    items: [
      { to: "/budgets", icon: _BudgetsIcon, keywords: ["oferta"] },
      { to: "/orders", icon: _OrdersIcon, keywords: ["orden"] },
      { to: "/invoices", icon: _InvoicesIcon, keywords: ["cobro"] },
      { to: "/reconciliation", icon: _ReconciliationIcon, keywords: ["conciliación", "diferencias"] },
      { to: "/ocr-review", icon: _OcrReviewIcon, keywords: ["revisión", "baja confianza"] },
      { to: "/admin/calidad", label: "Duplicados", icon: _DuplicatesIcon, keywords: ["duplicado"] },
      { to: "/admin/calidad", label: "Cuarentena", icon: _QuarantineIcon, roles: ["admin", "gestor"], keywords: ["cuarentena", "seguridad"] },
    ],
  },
  {
    id: "sistema",
    label: "Sistema",
    items: [
      { to: "/jobs", icon: _JobsIcon, roles: ["admin"], keywords: ["jobs", "celery", "cola"] },
      { to: "/admin/sistema", icon: _AdminSystemIcon, roles: ["admin"], keywords: ["salud", "infraestructura"] },
      { to: "/admin/acceso", icon: _AdminAccessIcon, roles: ["admin"], keywords: ["permisos", "rbac"] },
      { to: "/admin/integraciones", icon: _AdminIntegrationsIcon, roles: ["admin"], keywords: ["api", "cliente", "webhook"] },
      { to: "/admin/aprendizaje", icon: _AdminLearningIcon, roles: ["admin"], keywords: ["ia", "patrones"] },
    ],
  },
]

/**
 * Resolve every item's ``label`` from :data:`NAV_ROUTE_TITLES`. We
 * freeze the result so consumers cannot accidentally mutate the
 * shared navigation state.
 */
export const NAV_GROUPS: readonly ResolvedNavGroup[] = NAV_GROUPS_RAW.map((group) => ({
  ...group,
  items: group.items.map((item) => ({
    ...item,
    label: item.label ?? NAV_ROUTE_TITLES[item.to] ?? item.to,
  })),
})).map((g) => Object.freeze(g) as ResolvedNavGroup)
