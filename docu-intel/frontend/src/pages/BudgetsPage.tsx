import { useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDate } from "@/lib/utils"

export function BudgetsPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const budgets = useQuery({ queryKey: ["budgets"], queryFn: api.budgets })
  const acceptedWithoutOrder = useQuery({ queryKey: ["budgets", "accepted-without-order"], queryFn: api.acceptedBudgetsWithoutOrder })
  const activeId = selectedId ?? budgets.data?.[0]?.id ?? null
  const lines = useQuery({
    queryKey: ["budget-lines", activeId],
    queryFn: () => api.budgetLines(activeId ?? 0),
    enabled: activeId !== null,
  })

  return (
    <>
      <PageHeader title="Presupuestos" description="Extracción básica de cabecera, estado y líneas detectadas." />
      <Card>
        <CardHeader>
          <CardTitle>Aceptados sin pedido: {acceptedWithoutOrder.data?.length ?? 0}</CardTitle>
        </CardHeader>
        <CardContent>
          <BusinessTable rows={budgets.data ?? []} selectedId={activeId} onSelect={setSelectedId} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Líneas del presupuesto seleccionado</CardTitle>
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
                  <TableCell>{line.confidence ? `${Math.round(line.confidence * 100)}%` : "-"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  )
}

function BusinessTable({
  rows,
  selectedId,
  onSelect,
}: {
  rows: Awaited<ReturnType<typeof api.budgets>>
  selectedId: number | null
  onSelect: (id: number) => void
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Número</TableHead>
          <TableHead>Cliente</TableHead>
          <TableHead>Fecha</TableHead>
          <TableHead>Total</TableHead>
          <TableHead>Estado</TableHead>
          <TableHead>Confianza</TableHead>
          <TableHead></TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((budget) => (
          <TableRow key={budget.id} className={budget.id === selectedId ? "bg-muted/60" : undefined}>
            <TableCell>{budget.budget_number ?? "-"}</TableCell>
            <TableCell>{budget.client_name ?? "-"}</TableCell>
            <TableCell>{formatDate(budget.date)}</TableCell>
            <TableCell>{formatMoney(budget.total_amount)}</TableCell>
            <TableCell>{budget.status ?? "-"}</TableCell>
            <TableCell>{budget.confidence ? `${Math.round(budget.confidence * 100)}%` : "-"}</TableCell>
            <TableCell className="text-right">
              <Button variant="outline" size="sm" onClick={() => onSelect(budget.id)}>
                Ver líneas
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function formatMoney(value: number | null) {
  return value === null ? "-" : `${value.toFixed(2)} €`
}
