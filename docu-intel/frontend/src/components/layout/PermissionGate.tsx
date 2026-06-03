import { type ReactNode } from "react"
import { useAuth } from "@/hooks/useAuth"

type PermissionGateProps = {
  children: ReactNode
  /** Roles permitidos. Si no se especifica, se muestra para todos. */
  roles?: string[]
  /** Mensaje opcional si el usuario no tiene permiso */
  fallback?: ReactNode
}

export function PermissionGate({ children, roles, fallback }: PermissionGateProps) {
  const { user } = useAuth()

  if (!roles?.length) return <>{children}</>
  if (user && roles.includes(user.role)) return <>{children}</>

  return fallback ? <>{fallback}</> : null
}
