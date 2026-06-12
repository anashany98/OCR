import { Link } from "react-router-dom"
import { ArrowRight, FileSpreadsheet, FolderUp, ScanLine, Sparkles } from "lucide-react"

import { useAuth } from "@/hooks/useAuth"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

/**
 * "First run" empty state. Renders a 3-step getting-started card for users
 * who have zero documents, zero tasks, and zero searches in their recent
 * activity. Auto-detects by inspecting localStorage flag (so we don't pester
 * returning users) — pass `force` to override.
 */
export function OnboardingCallout({ force = false }: { force?: boolean }) {
  const { user } = useAuth()
  if (!user) return null

  const storageKey = `docu-intel:onboarding-dismissed:${user.id}`
  if (!force && typeof window !== "undefined" && window.localStorage.getItem(storageKey)) {
    return null
  }

  return (
    <Card className="overflow-hidden border-[var(--primary)]/30 bg-gradient-to-br from-[var(--primary-light)]/40 via-white to-white">
      <CardContent className="p-6">
        <div className="flex flex-col gap-5 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0 space-y-1.5">
            <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest text-[var(--primary)]">
              <Sparkles className="h-3 w-3" /> Bienvenida
            </p>
            <h2 className="text-[20px] font-semibold tracking-tight text-[var(--text-primary)]">
              Hola, {user.name.split(" ")[0]}. Configuremos tu puesto de trabajo.
            </h2>
            <p className="max-w-xl text-[13px] text-[var(--text-secondary)]">
              Docu-Intel procesa automáticamente presupuestos, pedidos y facturas. Sigue estos pasos
              para empezar a trabajar con tus documentos.
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="self-start text-[var(--text-muted)]"
            onClick={() => window.localStorage.setItem(storageKey, "1")}
          >
            Descartar
          </Button>
        </div>

        <ol className="mt-5 grid gap-3 sm:grid-cols-3">
          <Step
            number={1}
            icon={<FolderUp className="h-4 w-4" />}
            title="Sube tu primera carpeta"
            description="Arrastra archivos PDF o imágenes, o usa el botón Subir carpeta para mantener la estructura."
            to="/documents"
            cta="Ir a Documentos"
          />
          <Step
            number={2}
            icon={<ScanLine className="h-4 w-4" />}
            title="Escanea las carpetas vigiladas"
            description="Si tienes archivos en las carpetas de red configuradas, lánzalos al sistema con un clic."
            to="/documents"
            cta="Escanear ahora"
          />
          <Step
            number={3}
            icon={<FileSpreadsheet className="h-4 w-4" />}
            title="Revisa los resultados"
            description="Verifica la calidad OCR, corrige entidades y enlaza presupuestos con pedidos."
            to="/ocr-review"
            cta="Ir a Revisión OCR"
          />
        </ol>
      </CardContent>
    </Card>
  )
}

function Step({
  number,
  icon,
  title,
  description,
  to,
  cta,
}: {
  number: number
  icon: React.ReactNode
  title: string
  description: string
  to: string
  cta: string
}) {
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-[var(--border)] bg-white p-4">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[var(--primary)] text-[11px] font-bold text-white">
          {number}
        </span>
        <span className="text-[var(--primary)]">{icon}</span>
      </div>
      <h3 className="text-[14px] font-semibold text-[var(--text-primary)]">{title}</h3>
      <p className="flex-1 text-[12px] text-[var(--text-muted)]">{description}</p>
      <Button
        asChild
        variant="link"
        size="sm"
        className="h-auto justify-start gap-1 p-0 text-[12px] text-[var(--primary)]"
      >
        <Link to={to}>
          {cta}
          <ArrowRight className="h-3 w-3" />
        </Link>
      </Button>
    </li>
  )
}
