/**
 * Small summary card for the learning loop health.
 *
 * Shows pending / stale counts, oldest pending age, top noisy clients, and
 * learned pattern stats. Designed to be slotted into the admin page; fetched
 * via TanStack Query so it stays fresh.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Brain, ShieldAlert, Trash2 } from "lucide-react"

import { learningApi, type LearningHealthSnapshot } from "@/api/learning"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

function formatAge(seconds: number | null): string {
  if (seconds === null) return "—"
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3_600) return `${Math.round(seconds / 60)}m`
  if (seconds < 86_400) return `${Math.round(seconds / 3_600)}h`
  return `${Math.round(seconds / 86_400)}d`
}

export function LearningHealthCard() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError, refetch } = useQuery<LearningHealthSnapshot>({
    queryKey: ["learning", "health"],
    queryFn: () => learningApi.health(),
    refetchInterval: 60_000,
  })

  const handleTrigger = async () => {
    await learningApi.triggerAutoRejectStale()
    void queryClient.invalidateQueries({ queryKey: ["learning"] })
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-4 w-4" /> Salud del Learning Loop
          </CardTitle>
          <CardDescription>Cargando métricas…</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  if (isError || !data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-4 w-4" /> Salud del Learning Loop
          </CardTitle>
          <CardDescription className="text-red-500">
            No se pudo cargar la salud del bucle.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Reintentar
          </Button>
        </CardContent>
      </Card>
    )
  }

  const counts = data.suggestion_counts
  const patterns = data.learned_patterns

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-4 w-4" /> Salud del Learning Loop
          </CardTitle>
          <CardDescription>
            Sugerencias pendientes, zombis y patrones aprendidos activos.
          </CardDescription>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleTrigger}
          title={`Auto-rechaza sugerencias con más de ${data.stale_policy.threshold_days} días pendientes`}
        >
          <Trash2 className="mr-1 h-3 w-3" /> Auto-rechazar zombis
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <Metric label="Pendientes" value={counts.pending} />
          <Metric label="Aprobadas" value={counts.approved} />
          <Metric label="Rechazadas" value={counts.rejected} />
          <Metric label="Aplicadas" value={counts.applied} />
        </div>

        {data.stale_pending_count > 0 && (
          <div className="flex items-center gap-2 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            <ShieldAlert className="h-4 w-4" />
            <span>
              Hay <b>{data.stale_pending_count}</b> sugerencias zombis (más de{" "}
              {data.stale_policy.threshold_days} días). Pendiente más antigua:{" "}
              <b>{formatAge(data.oldest_pending_age_seconds)}</b>.
            </span>
          </div>
        )}

        {data.top_clients_by_pending.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Top clientes por volumen pendiente ({data.circuit_breaker.window_seconds / 3600}h)
            </h4>
            <ul className="mt-1 space-y-1 text-sm">
              {data.top_clients_by_pending.map((c) => (
                <li key={c.client_id ?? "none"} className="flex items-center justify-between">
                  <span>
                    Cliente #{c.client_id ?? "—"}
                    {c.pending > data.circuit_breaker.max_per_client && (
                      <Badge variant="warning" className="ml-2">
                        sobre el límite ({data.circuit_breaker.max_per_client})
                      </Badge>
                    )}
                  </span>
                  <span className="font-mono">{c.pending}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Patrones aprendidos
          </h4>
          <div className="mt-1 flex flex-wrap gap-2 text-sm">
            <Badge variant="success">{patterns.counts.active ?? 0} activos</Badge>
            <Badge variant="neutral">{patterns.counts.disabled ?? 0} desactivados</Badge>
            {patterns.top_active[0] && (
              <span className="text-xs text-muted-foreground">
                Más usado: <code>{patterns.top_active[0].pattern_value}</code> →{" "}
                {patterns.top_active[0].target_class} ({patterns.top_active[0].applied_count} usos)
              </span>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function Metric({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="rounded border border-slate-200 bg-slate-50 p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value ?? 0}</div>
    </div>
  )
}
