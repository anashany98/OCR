import { FormEvent, type ReactNode, useState } from "react"
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
  const appMode = import.meta.env.MODE || "local"

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
    <main className="grid min-h-screen bg-slate-950 p-4 text-slate-100 md:grid-cols-[minmax(0,1fr)_440px] md:p-0">
      <section className="hidden min-h-screen flex-col justify-between border-r border-white/10 p-10 md:flex">
        <div className="flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-md bg-cyan-500 text-white">
            <FileSearch />
          </div>
          <div>
            <p className="text-lg font-semibold">Docu-Intel</p>
            <p className="text-sm text-slate-400">Operación documental inteligente</p>
          </div>
        </div>
        <div className="max-w-xl">
          <p className="text-xs font-semibold uppercase tracking-normal text-cyan-300">Acceso interno</p>
          <h1 className="mt-3 text-4xl font-semibold leading-tight tracking-normal">Revisión, búsqueda y control documental en un único puesto de trabajo.</h1>
          <div className="mt-8 grid max-w-lg gap-3 sm:grid-cols-3">
            <Signal icon={<Database />} label="PostgreSQL" value="pgvector" />
            <Signal icon={<Server />} label="Backend" value="FastAPI" />
            <Signal icon={<LockKeyhole />} label="Entorno" value={appMode} />
          </div>
        </div>
        <p className="text-xs text-slate-500">Cambia credenciales y secretos antes de usarlo en red de empresa.</p>
      </section>

      <section className="flex min-h-[calc(100vh-2rem)] items-center justify-center md:min-h-screen">
        <Card className="w-full max-w-sm border-slate-200 shadow-2xl">
          <CardHeader>
            <div className="mb-2 flex size-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <FileSearch />
            </div>
            <CardTitle>Iniciar sesión</CardTitle>
            <CardDescription>Acceso a Docu-Intel. Usa tu email corporativo.</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="flex flex-col gap-3" onSubmit={onSubmit}>
              <label className="flex flex-col gap-1 text-sm">
                Email
                <Input value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="email" required />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                Contraseña
                <Input
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </label>
              {error ? <p className="rounded-md border border-destructive/40 bg-destructive/10 p-2 text-sm text-destructive">{error}</p> : null}
              <Button disabled={submitting}>{submitting ? "Entrando..." : "Entrar"}</Button>
            </form>
          </CardContent>
        </Card>
      </section>
    </main>
  )
}

function Signal({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/10 bg-white/5 p-3">
      <div className="mb-3 text-cyan-300 [&_svg]:h-4 [&_svg]:w-4">{icon}</div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-sm font-medium text-slate-100">{value}</p>
    </div>
  )
}
