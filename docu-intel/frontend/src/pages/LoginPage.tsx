import { FormEvent, useState } from "react"
import { Navigate } from "react-router-dom"
import { Database, FileSearch, LockKeyhole, Server } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { useAuth } from "@/hooks/useAuth"

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
    <div className="grid min-h-screen bg-[var(--bg-base)] md:grid-cols-[1fr_420px]">
      {/* Left panel - branding */}
      <section className="hidden min-h-screen flex-col justify-between border-r border-[var(--border)] bg-[var(--sidebar-bg)] p-10 md:flex">
        {/* Logo */}
        <div className="flex items-center gap-3 animate-fade-in-up">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--primary)] text-white shadow-lg shadow-[var(--primary)]/20">
            <FileSearch className="h-5 w-5" />
          </div>
          <div>
            <p className="text-[16px] font-semibold text-white">Docu-Intel</p>
            <p className="text-[12px] text-[var(--sidebar-muted)]">Operación documental inteligente</p>
          </div>
        </div>

        {/* Hero text */}
        <div className="max-w-lg animate-fade-in-up delay-100">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-[var(--primary)] mb-4">
            Control documental
          </p>
          <h1 className="text-3xl font-semibold leading-tight text-white tracking-tight">
            Revisión, búsqueda y control documental en un único puesto de trabajo.
          </h1>
          <p className="mt-4 text-[14px] text-[var(--sidebar-muted)] leading-relaxed">
            Procesa presupuestos, pedidos y planos con extracción OCR inteligente.
            Todo bajo control, todo accesible.
          </p>

          {/* Tech stack */}
          <div className="mt-8 grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <Database className="h-4 w-4 text-[var(--primary)] mb-3" />
              <p className="text-[11px] text-[var(--sidebar-muted)]">Base de datos</p>
              <p className="mt-0.5 text-[13px] font-semibold text-white">PostgreSQL</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <Server className="h-4 w-4 text-[var(--primary)] mb-3" />
              <p className="text-[11px] text-[var(--sidebar-muted)]">Backend</p>
              <p className="mt-0.5 text-[13px] font-semibold text-white">FastAPI</p>
            </div>
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <LockKeyhole className="h-4 w-4 text-[var(--primary)] mb-3" />
              <p className="text-[11px] text-[var(--sidebar-muted)]">Seguridad</p>
              <p className="mt-0.5 text-[13px] font-semibold text-white">JWT + RBAC</p>
            </div>
          </div>
        </div>

        {/* Footer */}
        <p className="text-[11px] text-[var(--sidebar-muted)] animate-fade-in-up delay-200">
          Cambia credenciales y secretos antes de usarlo en red de empresa.
        </p>
      </section>

      {/* Right panel - form */}
      <section className="flex min-h-[calc(100vh-2rem)] flex-col items-center justify-center p-6 md:min-h-screen md:p-10">
        <div className="w-full max-w-sm animate-fade-in-up">
          {/* Mobile logo */}
          <div className="mb-8 flex items-center gap-2 md:hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--primary)] text-white">
              <FileSearch className="h-4 w-4" />
            </div>
            <span className="text-[16px] font-semibold text-[var(--text-primary)]">Docu-Intel</span>
          </div>

          <Card className="border-[var(--border)] shadow-lg shadow-black/5">
            <CardHeader className="space-y-1 px-6 pt-6">
              <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--primary-light)] text-[var(--primary)]">
                <FileSearch className="h-5 w-5" />
              </div>
              <CardTitle className="text-[18px] font-semibold text-[var(--text-primary)]">Iniciar sesión</CardTitle>
              <CardDescription className="text-[13px] text-[var(--text-secondary)]">
                Accede a tu puesto de trabajo documental.
              </CardDescription>
            </CardHeader>
            <CardContent className="px-6 pb-6">
              <form className="space-y-4" onSubmit={onSubmit}>
                <div className="space-y-1.5">
                  <label className="text-[12px] font-medium text-[var(--text-secondary)]">Email corporativo</label>
                  <Input
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    type="email"
                    autoComplete="email"
                    placeholder="tecnico@empresa.com"
                    className="h-10 rounded-lg border-[var(--border)] bg-white text-[14px]"
                    required
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-[12px] font-medium text-[var(--text-secondary)]">Contraseña</label>
                  <Input
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    type="password"
                    autoComplete="current-password"
                    placeholder="••••••••"
                    className="h-10 rounded-lg border-[var(--border)] bg-white text-[14px]"
                    required
                  />
                </div>

                {error && (
                  <div className="flex items-center gap-2 rounded-lg border border-[#FECDD3] bg-[var(--rose-light)] px-3 py-2.5">
                    <span className="h-1.5 w-1.5 rounded-full bg-[var(--rose)]" />
                    <p className="text-[12px] text-[#9F1239]">{error}</p>
                  </div>
                )}

                <Button
                  type="submit"
                  disabled={submitting}
                  className="h-10 w-full rounded-lg text-[14px] font-medium"
                >
                  {submitting ? (
                    <span className="flex items-center gap-2">
                      <span className="h-3.5 w-3.5 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                      Entrando...
                    </span>
                  ) : (
                    "Entrar"
                  )}
                </Button>
              </form>
            </CardContent>
          </Card>

          <p className="mt-4 text-center text-[11px] text-[var(--text-muted)]">
            Sistema interno — acceso restringido a personal autorizado.
          </p>
        </div>
      </section>
    </div>
  )
}