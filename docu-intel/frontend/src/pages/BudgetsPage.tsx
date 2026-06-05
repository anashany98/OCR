import { useEffect, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"

import { api } from "@/api/client"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { PageHeader } from "@/components/layout/PageHeader"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDate, formatMoney } from "@/lib/utils"

export function BudgetsPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const linesRef = useRef<HTMLDivElement>(null)
  const budgets = useQuery({ queryKey: ["budgets"], queryFn: api.budgets })
  const acceptedWithoutOrder = useQuery({ queryKey: ["budgets", "accepted-without-order"], queryFn: api.acceptedBudgetsWithoutOrder })
  const activeId = selectedId ?? budgets.data?.[0]?.id ?? null
  const lines = useQuery({
    queryKey: ["budget-lines", activeId],
    queryFn: () => api.budgetLines(activeId ?? 0),
    enabled: activeId !== null,
  })

  // Auto-scroll to lines when a budget is selected
  useEffect(() => {
    if (selectedId !== null && linesRef.current) {
      linesRef.current.scrollIntoView({ behavior: "smooth", block: "start" })
    }
  }, [selectedId, lines.data])

  return (
    <>
      <Breadcrumbs items={[{ label: "Presupuestos" }]} />
      <PageHeader title="Presupuestos" description="Extracción básica de cabecera, estado y líneas detectadas." />
      <Card>
        <CardHeader>
          <CardTitle>Aceptados sin pedido: {acceptedWithoutOrder.data?.length ?? 0}</CardTitle>
        </CardHeader>
        <CardContent>
          <BusinessTable rows={budgets.data ?? []} selectedId={activeId} onSelect={setSelectedId} />
        </CardContent>
      </Card>
      <Card ref={linesRef}>
        <CardHeader>
          <CardTitle>
            Líneas del presupuesto seleccionado
            {selectedId !== null && lines.isLoading && (
              <span className="ml-2 text-sm text-muted-foreground">(cargando...)</span>
            )}
            {lines.isError && (
              <span className="ml-2 text-sm text-destructive">(error al cargar líneas)</span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {lines.isError ? (
            <p className="text-sm text-muted-foreground">No se pudieron cargar las líneas de este presupuesto.</p>
          ) : lines.data && lines.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">Este presupuesto no tiene líneas detectadas.</p>
          ) : (
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
          )}
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
