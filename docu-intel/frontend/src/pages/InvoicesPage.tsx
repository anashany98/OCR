import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ExternalLink, FileText } from "lucide-react"

import { api } from "@/api/client"
import { EmptyState } from "@/components/layout/EmptyState"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDate } from "@/lib/utils"

export function InvoicesPage() {
  const [query, setQuery] = useState("")
  const { data, isLoading } = useQuery({
    queryKey: ["invoices", query],
    queryFn: () => api.invoices({ q: query || undefined, limit: 100 }),
  })

  const items = data ?? []

  return (
    <>
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
        <PageHeader
          title="Facturas"
          description="Facturas detectadas en documentos con extracción de cabecera, importes, IVA y relaciones con pedidos y presupuestos."
        />
        <div className="relative w-full md:w-64">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar factura..."
            className="h-9"
          />
        </div>
      </div>

      <Card className="overflow-hidden">
        <CardHeader className="flex-row items-center justify-between border-b bg-slate-50/80">
          <div>
            <CardTitle>Facturas detectadas</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">{items.length} facturas encontradas</p>
          </div>
          <Badge variant="neutral">
            {items.filter((i) => i.invoice_number).length} con número
          </Badge>
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
                {items.map((invoice) => (
                  <TableRow key={invoice.id}>
                    <TableCell className="font-medium">
                      {invoice.invoice_number ?? (
                        <span className="text-muted-foreground">Sin número</span>
                      )}
                    </TableCell>
                    <TableCell>{invoice.supplier_name ?? "-"}</TableCell>
                    <TableCell>{invoice.client_name ?? "-"}</TableCell>
                    <TableCell className="whitespace-nowrap">{formatDate(invoice.date)}</TableCell>
                    <TableCell className="text-right font-medium">
                      {invoice.total_amount != null
                        ? new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(invoice.total_amount)
                        : "-"}
                    </TableCell>
                    <TableCell>{invoice.currency ?? "EUR"}</TableCell>
                    <TableCell>
                      {invoice.related_order_id ?? "-"}
                    </TableCell>
                    <TableCell>
                      {invoice.confidence != null
                        ? `${Math.round(invoice.confidence * 100)}%`
                        : "-"}
                    </TableCell>
                    <TableCell>
                      <Button asChild variant="outline" size="sm">
                        <Link to={`/documents/${invoice.document_id}`}>
                          <ExternalLink className="h-3.5 w-3.5" />
                          <span className="ml-1.5">Ver</span>
                        </Link>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {!items.length && !isLoading && (
                  <TableRow>
                    <TableCell colSpan={9} className="p-8">
                      <EmptyState
                        title="Sin facturas detectadas"
                        description="El sistema extrae facturas automáticamente de los documentos procesados. Sube facturas para que aparezcan aquí."
                        icon={<FileText className="h-5 w-5" />}
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
