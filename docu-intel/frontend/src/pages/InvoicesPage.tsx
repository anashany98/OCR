import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Download, ExternalLink, FileText, Search } from "lucide-react"

import { api } from "@/api/client"
import { EmptyState } from "@/components/layout/EmptyState"
import { PageHeader } from "@/components/layout/PageHeader"
import { MetricTile } from "@/components/layout/MetricTile"
import { EmptyInvoicesIllustration } from "@/components/illustrations/EditorialIllustrations"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { formatCompact, formatDate, formatMoney } from "@/lib/utils"
import { queryKeys } from "@/lib/queryKeys"
import type { Invoice } from "@/types/api"

const CURRENCY_OPTIONS = ["", "EUR", "USD", "GBP"]

export function InvoicesPage() {
  const [query, setQuery] = useState("")
  const [currency, setCurrency] = useState("")
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.invoices.list(query),
    queryFn: () => api.invoices({ q: query || undefined, limit: 200 }),
  })

  // ``data`` from react-query is referentially stable while the same
  // queryKey is in flight; ``data ?? []`` would otherwise allocate a
  // fresh array on every render and invalidate the ``useMemo`` below.
  // Wrapping in its own ``useMemo`` keeps the deps array honest.
  const items = useMemo(() => data ?? [], [data])

  // Client-side derived metrics
  const metrics = useMemo(() => deriveMetrics(items), [items])

  function exportCsv() {
    const headers = [
      "Número",
      "Proveedor",
      "Cliente",
      "Fecha",
      "Total",
      "Moneda",
      "Pedido",
      "Confianza",
    ]
    const rows = items.map((i) => [
      i.invoice_number ?? "",
      i.supplier_name ?? "",
      i.client_name ?? "",
      i.date ?? "",
      i.total_amount != null ? String(i.total_amount) : "",
      i.currency ?? "EUR",
      i.related_order_id ? String(i.related_order_id) : "",
      i.confidence != null ? String(i.confidence) : "",
    ])
    const csv = [headers, ...rows]
      .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","))
      .join("\n")
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = `docu-intel-facturas-${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      <PageHeader
        title="Facturas"
        description="Facturas detectadas con cabecera, importes, IVA y relaciones con pedidos y presupuestos."
      />

      {/* Metric tiles */}
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricTile
          title="Total facturado"
          value={formatMoney(metrics.totalEur)}
          meta={metrics.totalCount ? `${metrics.totalCount} facturas` : "Sin datos"}
          tone="success"
          icon={<FileText className="h-4 w-4" />}
        />
        <MetricTile
          title="Con nº de factura"
          value={metrics.withNumber}
          meta={`${metrics.totalCount ? Math.round((metrics.withNumber / metrics.totalCount) * 100) : 0}% cobertura`}
          tone={
            metrics.withNumber === metrics.totalCount && metrics.totalCount > 0
              ? "success"
              : "warning"
          }
        />
        <MetricTile
          title="Con pedido asociado"
          value={metrics.withOrder}
          meta={metrics.withoutOrder ? `${metrics.withoutOrder} huérfanas` : "Todas enlazadas"}
          tone={metrics.withoutOrder ? "warning" : "success"}
        />
        <MetricTile
          title="Confianza media"
          value={
            metrics.avgConfidence != null ? `${Math.round(metrics.avgConfidence * 100)}%` : "—"
          }
          meta={
            metrics.lowConfidence
              ? `${formatCompact(metrics.lowConfidence)} con OCR bajo`
              : "Sin problemas"
          }
          tone={metrics.lowConfidence ? "warning" : "neutral"}
        />
      </div>

      <Card className="overflow-hidden">
        <CardHeader className="flex-row items-center justify-between border-b">
          <div>
            <CardTitle>Facturas detectadas</CardTitle>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              {isLoading ? "Cargando…" : `${items.length} facturas en vista`}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
              <Input
                aria-label="Buscar factura"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar factura…"
                className="h-8 w-48 pl-8 text-[12px]"
              />
            </div>
            <select
              aria-label="Filtrar por moneda"
              className="h-8 rounded-md border border-[var(--border)] bg-white px-2 text-[12px]"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
            >
              {CURRENCY_OPTIONS.map((c) => (
                <option key={c} value={c}>
                  {c || "Todas las monedas"}
                </option>
              ))}
            </select>
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-[12px]"
              onClick={exportCsv}
              disabled={!items.length}
            >
              <Download className="mr-1 h-3.5 w-3.5" /> CSV
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nº Factura</TableHead>
                  <TableHead>Proveedor</TableHead>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Fecha</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                  <TableHead>Moneda</TableHead>
                  <TableHead>Pedido</TableHead>
                  <TableHead>Confianza</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items
                  .filter((i) => !currency || (i.currency ?? "EUR") === currency)
                  .map((invoice) => (
                    <InvoiceRow key={invoice.id} invoice={invoice} />
                  ))}
                {!items.length && !isLoading && (
                  <TableRow>
                    <TableCell colSpan={9} className="p-0">
                      <EmptyState
                        title="Sin facturas detectadas"
                        description="El sistema extrae facturas automáticamente de los documentos procesados. Sube facturas para que aparezcan aquí."
                        icon={<EmptyInvoicesIllustration />}
                        action="Ir a Documentos"
                        onAction={() => {
                          window.location.href = "/documents"
                        }}
                      />
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </>
  )
}

function InvoiceRow({ invoice }: { invoice: Invoice }) {
  const conf = invoice.confidence ?? null
  const confTone =
    conf == null ? "neutral" : conf < 0.7 ? "danger" : conf < 0.85 ? "warning" : "success"
  return (
    <TableRow>
      <TableCell className="font-medium">
        {invoice.invoice_number ? (
          invoice.invoice_number
        ) : (
          <Badge variant="warning" className="text-[10px]">
            Sin número
          </Badge>
        )}
      </TableCell>
      <TableCell>{invoice.supplier_name ?? "—"}</TableCell>
      <TableCell>{invoice.client_name ?? "—"}</TableCell>
      <TableCell className="whitespace-nowrap">{formatDate(invoice.date)}</TableCell>
      <TableCell className="text-right font-medium">{formatMoney(invoice.total_amount)}</TableCell>
      <TableCell>
        <Badge variant="neutral" className="text-[10px]">
          {invoice.currency ?? "EUR"}
        </Badge>
      </TableCell>
      <TableCell>
        {invoice.related_order_id ? (
          <span className="text-[12px] text-[var(--text-secondary)]">
            #{invoice.related_order_id}
          </span>
        ) : (
          <span className="text-[12px] text-[var(--amber)]">Sin enlazar</span>
        )}
      </TableCell>
      <TableCell>
        {conf != null ? (
          <Badge variant={confTone}>{Math.round(conf * 100)}%</Badge>
        ) : (
          <span className="text-[var(--text-muted)]">—</span>
        )}
      </TableCell>
      <TableCell>
        <Button
          asChild
          variant="ghost"
          size="icon"
          title="Ver documento"
          aria-label="Ver documento de la factura"
        >
          <Link to={`/documents/${invoice.document_id}`}>
            <ExternalLink className="h-4 w-4" aria-hidden="true" />
          </Link>
        </Button>
      </TableCell>
    </TableRow>
  )
}

type Metrics = {
  totalCount: number
  totalEur: number
  withNumber: number
  withOrder: number
  withoutOrder: number
  avgConfidence: number | null
  lowConfidence: number
}

function deriveMetrics(items: Invoice[]): Metrics {
  if (!items.length) {
    return {
      totalCount: 0,
      totalEur: 0,
      withNumber: 0,
      withOrder: 0,
      withoutOrder: 0,
      avgConfidence: null,
      lowConfidence: 0,
    }
  }
  const eur = items.filter((i) => (i.currency ?? "EUR") === "EUR" && i.total_amount != null)
  const totalEur = eur.reduce((sum, i) => sum + (i.total_amount ?? 0), 0)
  const confs = items.map((i) => i.confidence).filter((c): c is number => c != null)
  const avgConfidence = confs.length ? confs.reduce((a, b) => a + b, 0) / confs.length : null
  const withNumber = items.filter((i) => i.invoice_number).length
  const withOrder = items.filter((i) => i.related_order_id).length
  const lowConfidence = confs.filter((c) => c < 0.7).length
  return {
    totalCount: items.length,
    totalEur,
    withNumber,
    withOrder,
    withoutOrder: items.length - withOrder,
    avgConfidence,
    lowConfidence,
  }
}
