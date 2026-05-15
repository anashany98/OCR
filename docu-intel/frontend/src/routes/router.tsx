import { Navigate, createBrowserRouter } from "react-router-dom"

import { AppShell } from "@/components/layout/AppShell"
import { useAuth } from "@/hooks/useAuth"
import { AdminPage } from "@/pages/AdminPage"
import { BudgetsPage } from "@/pages/BudgetsPage"
import { ChatPage } from "@/pages/ChatPage"
import { DashboardPage } from "@/pages/DashboardPage"
import { DocumentDetailPage } from "@/pages/DocumentDetailPage"
import { DocumentsPage } from "@/pages/DocumentsPage"
import { JobsPage } from "@/pages/JobsPage"
import { LoginPage } from "@/pages/LoginPage"
import { OrdersPage } from "@/pages/OrdersPage"
import { OcrReviewPage } from "@/pages/OcrReviewPage"
import { PlansPage } from "@/pages/PlansPage"
import { SearchPage } from "@/pages/SearchPage"

function RequireAuth() {
  const { user, loading } = useAuth()
  if (loading) return <div className="p-6 text-sm text-muted-foreground">Cargando sesión...</div>
  if (!user) return <Navigate to="/login" replace />
  return <AppShell />
}

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: <RequireAuth />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "documents", element: <DocumentsPage /> },
      { path: "documents/:id", element: <DocumentDetailPage /> },
      { path: "ocr-review", element: <OcrReviewPage /> },
      { path: "search", element: <SearchPage /> },
      { path: "jobs", element: <JobsPage /> },
      { path: "budgets", element: <BudgetsPage /> },
      { path: "orders", element: <OrdersPage /> },
      { path: "plans", element: <PlansPage /> },
      { path: "chat", element: <ChatPage /> },
      { path: "admin", element: <AdminPage /> },
    ],
  },
])
