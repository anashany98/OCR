import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { Activity, BarChart3, FileText, CheckCircle2, Clock, AlertCircle, XCircle } from "lucide-react"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

const metricLabels = [
  ["documents_processed", "Procesados"],
  ["documents_pending", "Pendientes"],
  ["ocr_errors", "Errores OCR"],
  ["duplicates", "Duplicados"],
  ["accepted_budgets_without_order", "Presupuestos aceptados sin pedido"],
  ["plans_without_valid_scale", "Planos sin escala valida"],
] as const

export function DashboardPage() {
  const { data, isLoading } = useQuery({ queryKey: ["stats"], queryFn: api.stats })
  const errors = useQuery({ queryKey: ["ocr-errors"], queryFn: api.ocrErrors })
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts })
  const metrics = useQuery({ queryKey: ["processing-metrics"], queryFn: api.processingMetrics })

  return (
    <>
      <PageHeader title="Dashboard" description="Estado operativo de la ingesta documental." />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {metricLabels.map(([key, label]) => (
          <Card key={key}>
            <CardHeader className="pb-2">
              <CardTitle>{label}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{isLoading ? "-" : data?.[key] ?? 0}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {metrics.data && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex-row items-center gap-2 pb-2">
              <BarChart3 className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm">Documentos por estado</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {Object.entries(metrics.data.documents_by_status).map(([status, count]) => (
                <div key={status} className="flex items-center gap-1 rounded-md border px-2 py-1 text-xs">
                  {status === "processed" && <CheckCircle2 className="h-3 w-3 text-green-500" />}
                  {status === "pending" && <Clock className="h-3 w-3 text-yellow-500" />}
                  {status === "failed" && <XCircle className="h-3 w-3 text-red-500" />}
                  {status === "needs_review" && <AlertCircle className="h-3 w-3 text-orange-500" />}
                  <span className="font-medium">{count}</span>
                  <span className="text-muted-foreground">{status}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center gap-2 pb-2">
              <FileText className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm">Documentos por tipo</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {Object.entries(metrics.data.documents_by_type).map(([type, count]) => (
                <div key={type} className="rounded-md border px-2 py-1 text-xs">
                  <span className="font-medium">{count}</span>{" "}
                  <span className="text-muted-foreground">{type}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center gap-2 pb-2">
              <Activity className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm">Jobs por estado</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {Object.entries(metrics.data.jobs_by_status).map(([status, count]) => (
                <div key={status} className="rounded-md border px-2 py-1 text-xs">
                  <span className="font-medium">{count}</span>{" "}
                  <span className="text-muted-foreground">{status}</span>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex-row items-center gap-2 pb-2">
              <Activity className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm">Eventos auditados</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{metrics.data.audit_events_total}</p>
              <p className="text-xs text-muted-foreground">Total de eventos</p>
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Resumen</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm text-muted-foreground sm:grid-cols-3">
          <span>Total documentos: {data?.documents_total ?? "-"}</span>
          <span>Revision: {data?.documents_needs_review ?? "-"}</span>
          <span>Fallidos: {data?.documents_failed ?? "-"}</span>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Alertas operativas</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {(alerts.data ?? []).slice(0, 5).map((alert) => (
            <div key={alert.key} className="flex items-center justify-between gap-3 rounded-md border p-2 text-sm">
              <div>
                <p className="font-medium">{alert.title}</p>
                <p className="text-xs text-muted-foreground">{alert.description}</p>
              </div>
              <Button asChild variant="outline" size="sm">
                <Link to={alert.action_url}>{alert.count}</Link>
              </Button>
            </div>
          ))}
          {!alerts.data?.length ? <p className="text-sm text-muted-foreground">Sin alertas activas.</p> : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Errores y revision OCR</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {(errors.data ?? []).slice(0, 6).map((document) => (
            <div key={document.id} className="flex items-center justify-between gap-3 rounded-md border p-2 text-sm">
              <div className="min-w-0">
                <p className="truncate font-medium">{document.original_filename}</p>
                <p className="truncate text-xs text-muted-foreground">{document.error_message || "Requiere revision humana"}</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <StatusBadge status={document.status} />
                <Button asChild variant="outline" size="sm">
                  <Link to={`/documents/${document.id}`}>Abrir</Link>
                </Button>
              </div>
            </div>
          ))}
          {!errors.data?.length ? <p className="text-sm text-muted-foreground">No hay errores OCR ni documentos pendientes de revision.</p> : null}
        </CardContent>
      </Card>
    </>
  )
}
