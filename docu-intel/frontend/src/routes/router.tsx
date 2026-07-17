import { lazy, Suspense, type ReactNode } from "react"
import {
  Navigate,
  createBrowserRouter,
  isRouteErrorResponse,
  useRouteError,
} from "react-router-dom"

import { ErrorBoundary } from "@/components/ErrorBoundary"
import { AppShell } from "@/components/layout/AppShell"
import { LoadingState } from "@/components/layout/LoadingState"
import { PermissionGate } from "@/components/layout/PermissionGate"
import { useAuth } from "@/hooks/useAuth"
import { ADMIN_TABS, type AdminTab } from "@/navigation/config"

const ADMIN_ROLES = ["admin"]
const MANAGER_ROLES = ["admin", "gestor"]

// ---------------------------------------------------------------------------
// Lazy page registry.
//
// Every page exports a default React component; the loader returns
// a module with that component. The ``page`` / ``protectedPage`` helpers
// wrap a loader in ``<Suspense>`` so the route declaration stays a
// single line.
// ---------------------------------------------------------------------------

type PageLoader = () => Promise<unknown>

/**
 * Wrap a module loader so the resolved promise exposes the named
 * export as ``default``. React.lazy() reads ``module.default``;
 * our pages only have named exports (``export function Foo``), so
 * without this wrapper the lazy component receives ``undefined``.
 */
function lazyNamed<T>(loader: () => Promise<T>, exportName: keyof T): PageLoader {
  return () =>
    loader().then((module) => ({ default: module[exportName] as React.ComponentType<unknown> }))
}

const pages = {
  AdminPage: lazyNamed(() => import("@/pages/AdminPage"), "AdminPage"),
  AdminOperationalRoute: lazyNamed(
    () => import("@/pages/admin/AdminOperationalPage"),
    "AdminOperationalPage",
  ),
  AdminSystemRoute: lazyNamed(() => import("@/pages/admin/AdminSystemPage"), "AdminSystemPage"),
  AdminIntegrationsRoute: lazyNamed(
    () => import("@/pages/admin/AdminIntegrationsPage"),
    "AdminIntegrationsPage",
  ),
  AdminAccessRoute: lazyNamed(() => import("@/pages/admin/AdminAccessPage"), "AdminAccessPage"),
  AdminQualityRoute: lazyNamed(() => import("@/pages/admin/AdminQualityPage"), "AdminQualityPage"),
  AdminLearningRoute: lazyNamed(
    () => import("@/pages/admin/AdminLearningPage"),
    "AdminLearningPage",
  ),
  BudgetsPage: lazyNamed(() => import("@/pages/BudgetsPage"), "BudgetsPage"),
  ChatPage: lazyNamed(() => import("@/pages/chat/ChatPage"), "ChatPage"),
  DashboardPage: lazyNamed(() => import("@/pages/dashboard/DashboardPage"), "DashboardPage"),
  DocumentDetailPage: lazyNamed(
    () => import("@/pages/document/DocumentDetailPage"),
    "DocumentDetailPage",
  ),
  DocumentsPage: lazyNamed(() => import("@/pages/documents/DocumentsPage"), "DocumentsPage"),
  InvoicesPage: lazyNamed(() => import("@/pages/InvoicesPage"), "InvoicesPage"),
  JobsPage: lazyNamed(() => import("@/pages/JobsPage"), "JobsPage"),
  LoginPage: lazyNamed(() => import("@/pages/LoginPage"), "LoginPage"),
  NotFoundPage: lazyNamed(() => import("@/pages/NotFoundPage"), "NotFoundPage"),
  OrdersPage: lazyNamed(() => import("@/pages/OrdersPage"), "OrdersPage"),
  OcrReviewPage: lazyNamed(() => import("@/pages/ocr-review/OcrReviewPage"), "OcrReviewPage"),
  PlanoAnnotationPage: lazyNamed(
    () => import("@/pages/plano/PlanoAnnotationPage"),
    "PlanoAnnotationPage",
  ),
  PlansPage: lazyNamed(() => import("@/pages/plans/PlansPage"), "PlansPage"),
  ReconciliationPage: lazyNamed(() => import("@/pages/ReconciliationPage"), "ReconciliationPage"),
  SearchPage: lazyNamed(() => import("@/pages/search/SearchPage"), "SearchPage"),
  WorkInboxPage: lazyNamed(() => import("@/pages/work-inbox/WorkInboxPage"), "WorkInboxPage"),
}

function page(loader: PageLoader): ReactNode {
  const Component = lazy(loader as () => Promise<{ default: React.ComponentType<unknown> }>)
  return (
    <Suspense fallback={<LoadingState label="Cargando página..." />}>
      <Component />
    </Suspense>
  )
}

function protectedPage(loader: PageLoader, roles: string[]): ReactNode {
  const Component = lazy(loader as () => Promise<{ default: React.ComponentType<unknown> }>)
  return (
    <Suspense fallback={<LoadingState label="Cargando página..." />}>
      <RequireRole roles={roles}>
        <Component />
      </RequireRole>
    </Suspense>
  )
}

// ---------------------------------------------------------------------------
// Auth + error boundaries
// ---------------------------------------------------------------------------

function RequireAuth() {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center px-6">
        <LoadingState label="Cargando sesión..." />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return <AppShell />
}

function RequireRole({ roles, children }: { roles: string[]; children: ReactNode }) {
  const { user } = useAuth()
  if (user && roles.includes(user.role)) return <>{children}</>
  return (
    <PermissionGate
      roles={roles}
      mode="message"
      fallback={
        <div className="mx-auto mt-12 max-w-xl rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-4 text-sm text-[var(--text-secondary)]">
          No autorizado. Tu rol no tiene permisos para acceder a esta sección.
        </div>
      }
    >
      {children}
    </PermissionGate>
  )
}

function RouteErrorElement() {
  return (
    <ErrorBoundary>
      <RouteErrorFallback />
    </ErrorBoundary>
  )
}

function RouteErrorFallback() {
  const error = useRouteError()
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : "Error inesperado"

  return (
    <div className="mx-auto mt-12 max-w-xl rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-4 text-sm text-[var(--text-secondary)]">
      <h1 className="text-base font-semibold text-[var(--text-primary)]">
        No se pudo cargar esta vista
      </h1>
      <p className="mt-2">{message}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Admin sub-routes (generated from ADMIN_TABS so the sidebar, router
// and admin shell can never drift apart).
// ---------------------------------------------------------------------------

const adminChildLoaders: Record<AdminTab, PageLoader> = {
  operativa: pages.AdminOperationalRoute,
  sistema: pages.AdminSystemRoute,
  integraciones: pages.AdminIntegrationsRoute,
  acceso: pages.AdminAccessRoute,
  calidad: pages.AdminQualityRoute,
  aprendizaje: pages.AdminLearningRoute,
}

function adminRoute(tab: (typeof ADMIN_TABS)[number]) {
  const Component = lazy(
    adminChildLoaders[tab.id] as () => Promise<{ default: React.ComponentType<unknown> }>,
  )
  return {
    path: tab.id,
    element: (
      <Suspense fallback={<LoadingState label="Cargando sección..." />}>
        <Component />
      </Suspense>
    ),
    handle: { breadcrumb: tab.label },
  }
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

export const router = createBrowserRouter([
  { path: "/login", element: page(pages.LoginPage), errorElement: <RouteErrorElement /> },
  {
    path: "/",
    element: <RequireAuth />,
    errorElement: <RouteErrorElement />,
    children: [
      { index: true, element: page(pages.DashboardPage), handle: { breadcrumb: "Inicio" } },
      {
        path: "documents",
        element: page(pages.DocumentsPage),
        handle: { breadcrumb: "Documentos" },
      },
      {
        path: "documents/:id",
        element: page(pages.DocumentDetailPage),
        handle: { breadcrumb: (p: Record<string, string>) => `Doc #${p.id}` },
      },
      {
        path: "documents/:id/annotate-plan",
        element: protectedPage(pages.PlanoAnnotationPage, MANAGER_ROLES),
        handle: { breadcrumb: "Anotar plano" },
      },
      {
        path: "work-inbox",
        element: page(pages.WorkInboxPage),
        handle: { breadcrumb: "Bandeja de trabajo" },
      },
      {
        path: "ocr-review",
        element: page(pages.OcrReviewPage),
        handle: { breadcrumb: "Revisión OCR" },
      },
      { path: "search", element: page(pages.SearchPage), handle: { breadcrumb: "Búsqueda" } },
      {
        path: "jobs",
        element: protectedPage(pages.JobsPage, ADMIN_ROLES),
        handle: { breadcrumb: "Trabajos" },
      },
      { path: "budgets", element: page(pages.BudgetsPage), handle: { breadcrumb: "Presupuestos" } },
      { path: "orders", element: page(pages.OrdersPage), handle: { breadcrumb: "Pedidos" } },
      { path: "invoices", element: page(pages.InvoicesPage), handle: { breadcrumb: "Facturas" } },
      {
        path: "reconciliation",
        element: page(pages.ReconciliationPage),
        handle: { breadcrumb: "Conciliación" },
      },
      {
        path: "plans",
        element: protectedPage(pages.PlansPage, MANAGER_ROLES),
        handle: { breadcrumb: "Planos" },
      },
      { path: "chat", element: page(pages.ChatPage), handle: { breadcrumb: "Chat IA" } },
      {
        path: "admin",
        element: protectedPage(pages.AdminPage, ADMIN_ROLES),
        handle: { breadcrumb: "Administración" },
        children: [
          { index: true, element: <Navigate to="operativa" replace /> },
          ...ADMIN_TABS.map(adminRoute),
        ],
      },
      { path: "*", element: page(pages.NotFoundPage) },
    ],
  },
])
