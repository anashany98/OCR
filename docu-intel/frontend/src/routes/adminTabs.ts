import {
  Activity,
  Brain,
  KeyRound,
  ScanSearch,
  Settings,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react"

export const ADMIN_TABS = [
  { id: "operativa", label: "Operativa", icon: ShieldCheck },
  { id: "sistema", label: "Estado técnico", icon: Settings },
  { id: "integraciones", label: "Integraciones", icon: KeyRound },
  { id: "acceso", label: "Usuarios y permisos", icon: Users },
  { id: "calidad", label: "Calidad", icon: ScanSearch },
  { id: "aprendizaje", label: "Aprendizaje IA", icon: Brain },
  { id: "flujo-ocr", label: "Flujo OCR", icon: Activity },
] as const satisfies ReadonlyArray<{
  id: string
  label: string
  icon: LucideIcon
}>

export type AdminTab = (typeof ADMIN_TABS)[number]["id"]

export const ADMIN_TAB_LABELS: Record<AdminTab, string> = ADMIN_TABS.reduce(
  (acc, tab) => ({ ...acc, [tab.id]: tab.label }),
  {} as Record<AdminTab, string>,
)

export function normalizeAdminTab(value: string | null | undefined): AdminTab {
  return ADMIN_TABS.some((tab) => tab.id === value) ? (value as AdminTab) : "operativa"
}
