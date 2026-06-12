import { FormEvent, useState } from "react"
import { Navigate } from "react-router-dom"
import { ArrowRight, FileSearch, Lock, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useAuth } from "@/hooks/useAuth"
import { cn } from "@/lib/utils"

export function LoginPage() {
  const { user, login } = useAuth()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (user) return <Navigate to="/" replace />

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await login(email, password)
    } catch (currentError) {
      setError(currentError instanceof Error ? currentError.message : "No se pudo iniciar sesión")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="grid min-h-screen bg-[var(--bg-base)] md:grid-cols-2">
      {/* Left panel — editorial feature spread */}
      <section className="relative hidden flex-col justify-between overflow-hidden bg-[var(--ink)] p-12 text-[var(--bg-base)] md:flex">
        {/* Subtle paper texture via SVG noise */}
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.04]"
          style={{
            backgroundImage: "radial-gradient(circle at 1px 1px, currentColor 1px, transparent 0)",
            backgroundSize: "24px 24px",
          }}
        />

        <div className="relative flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--accent)] text-white shadow-lg">
            <FileSearch className="h-5 w-5" />
          </div>
          <div>
            <p className="font-display text-[18px] font-medium leading-tight tracking-tight">
              Docu-Intel
            </p>
            <p className="text-[11px] text-[var(--bg-base)]/60">Puesto de trabajo documental</p>
          </div>
        </div>

        <div className="relative max-w-lg space-y-8">
          <p className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--accent-soft)]">
            <Sparkles className="h-3 w-3" /> Sistema interno
          </p>
          <h1 className="font-display text-[40px] font-medium leading-[1.05] tracking-tight">
            Revisión, búsqueda y control documental en un único puesto de trabajo.
          </h1>
          <p className="max-w-md text-[14px] leading-relaxed text-[var(--bg-base)]/70">
            Procesa presupuestos, pedidos, facturas y planos con extracción OCR inteligente. Todo
            bajo control, todo accesible.
          </p>

          {/* Editorial pull-quote */}
          <blockquote className="border-l-2 border-[var(--accent)] pl-5 text-[13px] italic text-[var(--bg-base)]/80">
            “Lo importante no es la cantidad de papel que entra, sino cuántos documentos se quedan
            sin revisar.”
            <footer className="mt-2 not-italic text-[11px] text-[var(--bg-base)]/50">
              — principio de operación
            </footer>
          </blockquote>
        </div>

        <div className="relative flex items-center justify-between text-[11px] text-[var(--bg-base)]/50">
          <span>Sistema interno · acceso restringido</span>
          <span>v0.1</span>
        </div>
      </section>

      {/* Right panel — form on cream paper */}
      <section className="flex min-h-screen flex-col items-center justify-center p-6 md:p-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2 md:hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--accent)] text-white">
              <FileSearch className="h-4 w-4" />
            </div>
            <span className="font-display text-[16px] font-medium">Docu-Intel</span>
          </div>

          <Card className="border-[var(--border)] shadow-md">
            <CardHeader className="px-7 pt-7">
              <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--accent-faint)] text-[var(--accent)]">
                <Lock className="h-5 w-5" />
              </div>
              <CardTitle className="text-[20px]">Iniciar sesión</CardTitle>
              <CardDescription>Accede a tu puesto de trabajo documental.</CardDescription>
            </CardHeader>
            <CardContent className="px-7 pb-7">
              <form className="space-y-4" onSubmit={onSubmit}>
                <div className="space-y-1.5">
                  <label
                    className="text-[12px] font-medium text-[var(--text-secondary)]"
                    htmlFor="email"
                  >
                    Email corporativo
                  </label>
                  <Input
                    id="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    type="email"
                    autoComplete="email"
                    placeholder="tecnico@empresa.com"
                    className="h-11 rounded-md"
                    required
                  />
                </div>
                <div className="space-y-1.5">
                  <label
                    className="text-[12px] font-medium text-[var(--text-secondary)]"
                    htmlFor="password"
                  >
                    Contraseña
                  </label>
                  <Input
                    id="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    type="password"
                    autoComplete="current-password"
                    placeholder="••••••••"
                    className="h-11 rounded-md"
                    required
                  />
                </div>

                {error && (
                  <div
                    role="alert"
                    className="flex items-start gap-2 rounded-md border border-[var(--danger)]/30 bg-[var(--danger-faint)] px-3 py-2.5 text-[12px] text-[var(--text-on-danger)]"
                  >
                    <span className="mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-[var(--danger)]" />
                    <span className="leading-relaxed">{error}</span>
                  </div>
                )}

                <Button
                  type="submit"
                  disabled={submitting}
                  className={cn("h-11 w-full text-[14px]")}
                >
                  {submitting ? (
                    <span className="flex items-center gap-2">
                      <span className="h-3.5 w-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                      Entrando…
                    </span>
                  ) : (
                    <span className="flex items-center gap-2">
                      Entrar <ArrowRight className="h-4 w-4" />
                    </span>
                  )}
                </Button>
              </form>
            </CardContent>
          </Card>

          <p className="mt-6 text-center text-[11px] text-[var(--text-muted)]">
            Sistema interno — acceso restringido a personal autorizado.
          </p>
        </div>
      </section>
    </div>
  )
}
