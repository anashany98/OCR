import { useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { api } from "@/api/client"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { PageHeader } from "@/components/layout/PageHeader"
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
import { formatDate, formatMoney } from "@/lib/utils"

export function OrdersPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const { data } = useQuery({ queryKey: ["orders"], queryFn: api.orders })
  const activeId = selectedId ?? data?.[0]?.id ?? null
  const lines = useQuery({
    queryKey: ["order-lines", activeId],
    queryFn: () => api.orderLines(activeId ?? 0),
    enabled: activeId !== null,
  })

  return (
    <>
      <Breadcrumbs items={[{ label: "Pedidos" }]} />
      <PageHeader
        title="Pedidos"
        description="Extracción básica de proveedor, cliente, relación con presupuesto y líneas."
      />
      <Card>
        <CardHeader>
          <CardTitle>Pedidos detectados</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Número</TableHead>
                <TableHead>Proveedor</TableHead>
                <TableHead>Cliente</TableHead>
                <TableHead>Fecha</TableHead>
                <TableHead>Total</TableHead>
                <TableHead>Presupuesto relacionado</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data ?? []).map((order) => (
                <TableRow
                  key={order.id}
                  className={order.id === activeId ? "bg-muted/60" : undefined}
                >
                  <TableCell>{order.order_number ?? "-"}</TableCell>
                  <TableCell>{order.supplier_name ?? "-"}</TableCell>
                  <TableCell>{order.client_name ?? "-"}</TableCell>
                  <TableCell>{formatDate(order.date)}</TableCell>
                  <TableCell>{formatMoney(order.total_amount)}</TableCell>
                  <TableCell>{order.related_budget_id ?? "-"}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm" onClick={() => setSelectedId(order.id)}>
                      Ver líneas
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Líneas del pedido seleccionado</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Referencia</TableHead>
                <TableHead>Descripción</TableHead>
                <TableHead>Cantidad</TableHead>
                <TableHead>Ud.</TableHead>
                <TableHead>Precio ud.</TableHead>
                <TableHead>Total</TableHead>
                <TableHead>Confianza</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(lines.data ?? []).map((line) => (
                <TableRow key={line.id}>
                  <TableCell>{line.reference ?? "-"}</TableCell>
                  <TableCell>{line.description ?? "-"}</TableCell>
                  <TableCell>{line.quantity ?? "-"}</TableCell>
                  <TableCell>{line.unit ?? "-"}</TableCell>
                  <TableCell>{formatMoney(line.unit_price)}</TableCell>
                  <TableCell>{formatMoney(line.total_price)}</TableCell>
                  <TableCell>
                    {line.confidence ? `${Math.round(line.confidence * 100)}%` : "-"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  )
}
