import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, ExternalLink, RefreshCw, Scale, XCircle } from "lucide-react"

import { api } from "@/api/client"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { EmptyState } from "@/components/layout/EmptyState"
import { MetricTile } from "@/components/layout/MetricTile"
import { PageHeader } from "@/components/layout/PageHeader"
import { Badge, type BadgeProps } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatDate } from "@/lib/utils"
import { notify } from "@/lib/toast"
import type { ReconciliationIssue } from "@/types/api"

export function ReconciliationPage() {
  const queryClient = useQueryClient()
  const issues = useQuery({
    queryKey: ["reconciliation-issues"],
    queryFn: api.reconciliationIssues,
    refetchInterval: 30000,
  })
  const generate = useMutation({
    mutationFn: api.generateReconciliationIssues,
    onSuccess: (items) => {
      queryClient.invalidateQueries({ queryKey: ["reconciliation-issues"] })
      notify.success(`Incidencias generadas`, `${items.length} diferencias detectadas.`)
    },
    onError: (err) => notify.error(err, "No se pudieron generar las incidencias"),
  })
  const update = useMutation({
    mutationFn: ({ id, status }: { id: number; status: "reviewed" | "ignored" | "pending" }) =>
      api.updateReconciliationIssue(id, {
        status,
        resolution_notes: status === "reviewed" ? "Revisado desde conciliación" : null,
      }),
    onSuccess: (_, vars) => {
      queryClient.invalidateQueries({ queryKey: ["reconciliation-issues"] })
      const label =
        vars.status === "reviewed"
          ? "marcada como revisada"
          : vars.status === "ignored"
            ? "ignorada"
            : "marcada como pendiente"
      notify.success(`Incidencia ${label}`)
    },
    onError: (err) => notify.error(err, "No se pudo actualizar la incidencia"),
  })

  const items = issues.data ?? []
  const pending = items.filter((item) => item.status === "pending").length
  const critical = items.filter(
    (item) => item.severity === "critical" || item.kind.includes("amount"),
  ).length
  const reviewed = items.filter((item) => item.status === "reviewed").length

  return (
    <>
      <Breadcrumbs items={[{ label: "Incidencias" }]} />
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
        <PageHeader
          title="Conciliación"
          description="Cruce operativo entre presupuestos, pedidos y facturas con resolución trazable."
        />
        <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
          <RefreshCw data-icon="inline-start" />
          Generar incidencias
        </Button>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <MetricTile
          title="Pendientes"
          value={pending}
          meta="Diferencias por revisar"
          tone={pending ? "warning" : "success"}
        />
        <MetricTile
          title="Críticas"
          value={critical}
          meta="Importes o enlaces sensibles"
          tone={critical ? "danger" : "neutral"}
        />
        <MetricTile title="Revisadas" value={reviewed} meta="Cerradas por gestión" tone="success" />
      </div>

      <Card className="overflow-hidden">
        <CardHeader className="flex-row items-center justify-between border-b bg-slate-50/80">
          <CardTitle>Incidencias de negocio</CardTitle>
          <Badge variant="neutral">{items.length} registros</Badge>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Estado</TableHead>
                  <TableHead>Incidencia</TableHead>
                  <TableHead>Importes</TableHead>
                  <TableHead>Vínculos</TableHead>
                  <TableHead>Fecha</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((issue) => (
                  <TableRow key={issue.id}>
                    <TableCell>
                      <Badge variant={statusVariant(issue.status)}>{issue.status}</Badge>
                    </TableCell>
                    <TableCell>
                      <p className="font-medium">{issue.title}</p>
                      <p className="max-w-[520px] text-xs text-muted-foreground">
                        {issue.description}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">{issue.kind}</p>
                    </TableCell>
                    <TableCell className="text-sm">
                      <AmountLine label="Esperado" value={issue.expected_amount} />
                      <AmountLine label="Actual" value={issue.actual_amount} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      <p>Presupuesto: {issue.budget_id ?? "-"}</p>
                      <p>Pedido: {issue.order_id ?? "-"}</p>
                      <p>Factura: {issue.invoice_id ?? "-"}</p>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(issue.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        {issue.document_id ? (
                          <Button asChild variant="outline" size="sm">
                            <Link to={`/documents/${issue.document_id}`}>
                              <ExternalLink data-icon="inline-start" />
                              Fuente
                            </Link>
                          </Button>
                        ) : null}
                        <Button
                          variant="outline"
                          size="icon"
                          onClick={() => update.mutate({ id: issue.id, status: "ignored" })}
                          title="Ignorar"
                          aria-label="Ignorar incidencia"
                        >
                          <XCircle aria-hidden="true" />
                        </Button>
                        <Button
                          size="icon"
                          onClick={() => update.mutate({ id: issue.id, status: "reviewed" })}
                          title="Marcar revisada"
                          aria-label="Marcar como revisada"
                        >
                          <CheckCircle2 aria-hidden="true" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
                {!items.length ? (
                  <TableRow>
                    <TableCell colSpan={6} className="p-8">
                      <EmptyState
                        title="Sin incidencias de conciliación"
                        description="Ejecuta el generador para cruzar presupuestos aceptados, pedidos y facturas."
                        icon={<Scale className="h-5 w-5" />}
                      />
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {issues.isError ? <p className="text-sm text-destructive">{issues.error.message}</p> : null}
      {generate.isError ? (
        <p className="text-sm text-destructive">{generate.error.message}</p>
      ) : null}
    </>
  )
}

function AmountLine({ label, value }: { label: string; value: number | null }) {
  return (
    <p className="whitespace-nowrap">
      <span className="text-muted-foreground">{label}: </span>
      <span className="font-medium">
        {value == null
          ? "-"
          : new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(value)}
      </span>
    </p>
  )
}

function statusVariant(status: ReconciliationIssue["status"]): BadgeProps["variant"] {
  if (status === "reviewed") return "success"
  if (status === "ignored") return "neutral"
  return "warning"
}
