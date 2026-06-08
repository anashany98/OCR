import { Link } from "react-router-dom"

import { Button } from "@/components/ui/button"

export function NotFoundPage() {
  return (
    <div className="mx-auto flex min-h-[55vh] max-w-xl flex-col items-center justify-center text-center">
      <p className="text-sm font-medium text-[var(--text-muted)]">404</p>
      <h1 className="mt-2 text-2xl font-semibold text-[var(--text-primary)]">Página no encontrada</h1>
      <p className="mt-2 text-sm text-[var(--text-secondary)]">
        La ruta no existe o ya no está disponible.
      </p>
      <Button asChild className="mt-5">
        <Link to="/">Volver al dashboard</Link>
      </Button>
    </div>
  )
}
