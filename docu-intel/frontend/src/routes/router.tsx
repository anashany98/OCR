import { lazy, Suspense, type ReactNode } from "react"
import { Navigate, createBrowserRouter, isRouteErrorResponse, useRouteError } from "react-router-dom"

import { ErrorBoundary } from "@/components/ErrorBoundary"
import { AppShell } from "@/components/layout/AppShell"
import { LoadingState } from "@/components/layout/LoadingState"
import { PermissionGate } from "@/components/layout/PermissionGate"
import { useAuth } from "@/hooks/useAuth"

const AdminPage = lazy(() => import("@/pages/AdminPage").then((module) => ({ default: module.AdminPage })))
const BudgetsPage = lazy(() => import("@/pages/BudgetsPage").then((module) => ({ default: module.BudgetsPage })))
const ChatPage = lazy(() => import("@/pages/ChatPage").then((module) => ({ default: module.ChatPage })))
const DashboardPage = lazy(() => import("@/pages/DashboardPage").then((module) => ({ default: module.DashboardPage })))
const DocumentDetailPage = lazy(() => import("@/pages/DocumentDetailPage").then((module) => ({ default: module.DocumentDetailPage })))
const DocumentsPage = lazy(() => import("@/pages/DocumentsPage").then((module) => ({ default: module.DocumentsPage })))
const InvoicesPage = lazy(() => import("@/pages/InvoicesPage").then((module) => ({ default: module.InvoicesPage })))
const JobsPage = lazy(() => import("@/pages/JobsPage").then((module) => ({ default: module.JobsPage })))
const LoginPage = lazy(() => import("@/pages/LoginPage").then((module) => ({ default: module.LoginPage })))
const NotFoundPage = lazy(() => import("@/pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage })))
const OrdersPage = lazy(() => import("@/pages/OrdersPage").then((module) => ({ default: module.OrdersPage })))
const OcrReviewPage = lazy(() => import("@/pages/OcrReviewPage").then((module) => ({ default: module.OcrReviewPage })))
const PlanoAnnotationPage = lazy(() =>
  import("@/pages/PlanoAnnotationPage").then((module) => ({ default: module.PlanoAnnotationPage })),
)
const PlansPage = lazy(() => import("@/pages/PlansPage").then((module) => ({ default: module.PlansPage })))
const ReconciliationPage = lazy(() => import("@/pages/ReconciliationPage").then((module) => ({ default: module.ReconciliationPage })))
const SearchPage = lazy(() => import("@/pages/SearchPage").then((module) => ({ default: module.SearchPage })))
const WorkInboxPage = lazy(() => import("@/pages/WorkInboxPage").then((module) => ({ default: module.WorkInboxPage })))

const ADMIN_ROLES = ["admin"]
const MANAGER_ROLES = ["admin", "gestor"]

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

function RouteSuspense({ children }: { children: ReactNode }) {
  return <Suspense fallback={<LoadingState label="Cargando página..." />}>{children}</Suspense>
}

function page(element: ReactNode) {
  return <RouteSuspense>{element}</RouteSuspense>
}

function protectedPage(element: ReactNode, roles: string[]) {
  return page(<RequireRole roles={roles}>{element}</RequireRole>)
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
      <h1 className="text-base font-semibold text-[var(--text-primary)]">No se pudo cargar esta vista</h1>
      <p className="mt-2">{message}</p>
    </div>
  )
}

export const router = createBrowserRouter([
  { path: "/login", element: page(<LoginPage />), errorElement: <RouteErrorElement /> },
  {
    path: "/",
    element: <RequireAuth />,
    errorElement: <RouteErrorElement />,
    children: [
      { index: true, element: page(<DashboardPage />), handle: { title: "Dashboard" } },
      { path: "documents", element: page(<DocumentsPage />), handle: { title: "Documentos" } },
      { path: "documents/:id", element: page(<DocumentDetailPage />), handle: { title: "Detalle de documento" } },
      { path: "documents/:id/annotate-plan", element: protectedPage(<PlanoAnnotationPage />, MANAGER_ROLES), handle: { title: "Anotar plano" } },
      { path: "work-inbox", element: page(<WorkInboxPage />), handle: { title: "Tareas" } },
      { path: "ocr-review", element: page(<OcrReviewPage />), handle: { title: "Revisión OCR" } },
      { path: "search", element: page(<SearchPage />), handle: { title: "Buscar" } },
      { path: "jobs", element: protectedPage(<JobsPage />, ADMIN_ROLES), handle: { title: "Procesamiento" } },
      { path: "budgets", element: page(<BudgetsPage />), handle: { title: "Presupuestos" } },
      { path: "orders", element: page(<OrdersPage />), handle: { title: "Pedidos" } },
      { path: "invoices", element: page(<InvoicesPage />), handle: { title: "Facturas" } },
      { path: "reconciliation", element: page(<ReconciliationPage />), handle: { title: "Incidencias" } },
      { path: "plans", element: protectedPage(<PlansPage />, MANAGER_ROLES), handle: { title: "Planos" } },
      { path: "chat", element: page(<ChatPage />), handle: { title: "Preguntar a documentos" } },
      { path: "admin", element: protectedPage(<AdminPage />, ADMIN_ROLES), handle: { title: "Administración" } },
      { path: "*", element: page(<NotFoundPage />), handle: { title: "No encontrado" } },
    ],
  },
])
