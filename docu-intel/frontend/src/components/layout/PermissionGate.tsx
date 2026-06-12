import { type ReactNode } from "react"
import { Lock } from "lucide-react"

import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

type PermissionGateProps = {
  children: ReactNode
  /** Roles permitidos. Si no se especifica, se muestra para todos. */
  roles?: string[]
  /**
   * "hide" (default): oculta el contenido si el usuario no tiene permiso.
   * "disable": muestra el contenido deshabilitado con un candado y tooltip.
   * "message": muestra un mensaje en lugar del contenido.
   */
  mode?: "hide" | "disable" | "message"
  /** Mensaje opcional si el usuario no tiene permiso. */
  fallback?: ReactNode
  /** Texto del tooltip en modo "disable". */
  lockReason?: string
  /** Optional className applied to the wrapper. */
  className?: string
}

const ROLE_LABELS: Record<string, string> = {
  admin: "administrador",
  gestor: "gestor",
  operario: "operario",
  auditor: "auditor",
}

function buildLockReason(roles: string[], custom?: string) {
  if (custom) return custom
  const formatted = roles.map((r) => ROLE_LABELS[r] ?? r).join(" o ")
  return `Requiere rol de ${formatted}`
}

export function PermissionGate({
  children,
  roles,
  mode = "hide",
  fallback,
  lockReason,
  className,
}: PermissionGateProps) {
  const { user } = useAuth()

  if (!roles?.length) return <>{children}</>
  if (user && roles.includes(user.role)) return <>{children}</>

  if (mode === "disable") {
    return (
      <span
        className={cn("relative inline-flex cursor-not-allowed select-none", className)}
        title={buildLockReason(roles, lockReason)}
        aria-disabled
      >
        <span className="pointer-events-none opacity-50">{children}</span>
        <Lock className="pointer-events-none absolute right-1 top-1 h-3 w-3 text-[var(--text-muted)]" />
      </span>
    )
  }

  if (mode === "message") {
    if (fallback) return <>{fallback}</>
    return (
      <div
        role="note"
        className={cn(
          "flex items-center gap-2 rounded-md border border-dashed border-[var(--border)] bg-[var(--bg-surface-2)] px-3 py-2 text-[12px] text-[var(--text-muted)]",
          className,
        )}
      >
        <Lock className="h-3.5 w-3.5 flex-shrink-0" />
        <span>{buildLockReason(roles, lockReason)}</span>
      </div>
    )
  }

  // mode === "hide"
  return fallback ? <>{fallback}</> : null
}
