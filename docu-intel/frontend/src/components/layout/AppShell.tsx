import { NavLink, Outlet } from "react-router-dom"
import {
  Bot,
  BriefcaseBusiness,
  ClipboardList,
  FileSearch,
  Files,
  Gauge,
  Eye,
  LayoutDashboard,
  LogOut,
  Map,
  Settings,
  UploadCloud,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/documents", label: "Documentos", icon: Files },
  { to: "/ocr-review", label: "Revisión OCR", icon: Eye },
  { to: "/search", label: "Búsqueda", icon: FileSearch },
  { to: "/jobs", label: "Jobs", icon: Gauge },
  { to: "/budgets", label: "Presupuestos", icon: BriefcaseBusiness },
  { to: "/orders", label: "Pedidos", icon: ClipboardList },
  { to: "/plans", label: "Planos", icon: Map },
  { to: "/chat", label: "Chat IA", icon: Bot },
  { to: "/admin", label: "Administración", icon: Settings },
]

export function AppShell() {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r bg-card md:flex md:flex-col">
        <div className="flex h-14 items-center gap-2 border-b px-4">
          <UploadCloud className="text-primary" data-icon="inline-start" />
          <div>
            <p className="text-sm font-semibold leading-none">Docu-Intel</p>
            <p className="text-xs text-muted-foreground">Inteligencia documental</p>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  "flex h-9 items-center gap-2 rounded-md px-3 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
                  isActive && "bg-secondary text-foreground",
                )
              }
            >
              <item.icon data-icon="inline-start" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t p-3">
          <p className="truncate text-sm font-medium">{user?.name}</p>
          <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
          <Button className="mt-3 w-full" variant="outline" size="sm" onClick={logout}>
            <LogOut data-icon="inline-start" />
            Salir
          </Button>
        </div>
      </aside>
      <main className="min-h-screen md:pl-64">
        <div className="border-b bg-card px-4 py-3 md:hidden">
          <p className="text-sm font-semibold">Docu-Intel</p>
        </div>
        <div className="mx-auto flex max-w-7xl flex-col gap-5 p-4 md:p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
