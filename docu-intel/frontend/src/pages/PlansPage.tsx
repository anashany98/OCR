import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ExternalLink, Ruler, Save } from "lucide-react"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export function PlansPage() {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [scaleText, setScaleText] = useState("")
  const plans = useQuery({ queryKey: ["plans"], queryFn: api.plans })
  const selectedPlan = useMemo(
    () => plans.data?.find((plan) => plan.id === selectedId) ?? plans.data?.[0] ?? null,
    [plans.data, selectedId],
  )
  const rooms = useQuery({
    queryKey: ["plans", selectedPlan?.id, "rooms"],
    queryFn: () => api.planRooms(selectedPlan!.id),
    enabled: Boolean(selectedPlan),
  })
  const dimensions = useQuery({
    queryKey: ["plans", selectedPlan?.id, "dimensions"],
    queryFn: () => api.planDimensions(selectedPlan!.id),
    enabled: Boolean(selectedPlan),
  })
  const scaleMutation = useMutation({
    mutationFn: () => {
      const ratio = parseScaleRatio(scaleText)
      return api.updatePlanScale(selectedPlan!.id, {
        scale_text: scaleText.trim() || null,
        scale_ratio: ratio,
        scale_confidence: ratio ? 1 : null,
        unit: "m",
        has_valid_scale: Boolean(ratio),
      })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plans"] }),
  })
  const roomMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) => api.updatePlanRoom(id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["plans", selectedPlan?.id, "rooms"] })
    },
  })

  useEffect(() => {
    if (selectedPlan) setScaleText(selectedPlan.scale_text ?? "")
  }, [selectedPlan])

  return (
    <>
      <PageHeader title="Planos" description="Escalas, habitaciones y cotas extraídas con revisión manual." />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(420px,0.9fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Planos registrados</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Proyecto</TableHead>
                  <TableHead>Escala</TableHead>
                  <TableHead>Confianza</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Fuente</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(plans.data ?? []).map((plan) => (
                  <TableRow
                    key={plan.id}
                    className={selectedPlan?.id === plan.id ? "bg-muted/60" : ""}
                    onClick={() => setSelectedId(plan.id)}
                  >
                    <TableCell className="font-medium">{plan.project_name ?? `Plano #${plan.id}`}</TableCell>
                    <TableCell>{plan.scale_text ?? "-"}</TableCell>
                    <TableCell>{plan.scale_confidence ? `${Math.round(plan.scale_confidence * 100)}%` : "-"}</TableCell>
                    <TableCell>
                      <Badge variant={plan.has_valid_scale ? "success" : "warning"}>
                        {plan.has_valid_scale ? "válida" : "revisar"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Button asChild variant="outline" size="sm">
                        <Link to={`/documents/${plan.document_id}`}>
                          <ExternalLink data-icon="inline-start" />
                          Abrir
                        </Link>
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
            <CardTitle>{selectedPlan ? selectedPlan.project_name ?? `Plano #${selectedPlan.id}` : "Detalle del plano"}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {selectedPlan ? (
              <>
                <div className="grid gap-2 rounded-md border p-3">
                  <label className="text-xs font-medium text-muted-foreground">Escala manual</label>
                  <div className="flex gap-2">
                    <Input value={scaleText} onChange={(event) => setScaleText(event.target.value)} placeholder="1:50" />
                    <Button onClick={() => scaleMutation.mutate()} disabled={scaleMutation.isPending}>
                      <Save data-icon="inline-start" />
                      Guardar
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Sin escala válida no se convierten geometrías de píxeles a metros. Las superficies OCR se conservan como texto fuente.
                  </p>
                </div>

                <section className="space-y-2">
                  <h3 className="flex items-center gap-2 text-sm font-semibold">
                    <Ruler className="size-4" />
                    Habitaciones
                  </h3>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Nombre</TableHead>
                        <TableHead>m²</TableHead>
                        <TableHead>Ancho</TableHead>
                        <TableHead>Largo</TableHead>
                        <TableHead>Estado</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(rooms.data ?? []).map((room) => (
                        <TableRow key={room.id}>
                          <TableCell>
                            <Input
                              defaultValue={room.name ?? ""}
                              onBlur={(event) => roomMutation.mutate({ id: room.id, payload: { name: event.currentTarget.value || null } })}
                            />
                          </TableCell>
                          <TableCell>
                            <Input
                              type="number"
                              step="0.01"
                              defaultValue={room.area_m2 ?? ""}
                              onBlur={(event) => roomMutation.mutate({ id: room.id, payload: { area_m2: numberOrNull(event.currentTarget.value) } })}
                            />
                          </TableCell>
                          <TableCell>
                            <Input
                              type="number"
                              step="0.01"
                              defaultValue={room.width_m ?? ""}
                              onBlur={(event) => roomMutation.mutate({ id: room.id, payload: { width_m: numberOrNull(event.currentTarget.value), source: "human" } })}
                            />
                          </TableCell>
                          <TableCell>
                            <Input
                              type="number"
                              step="0.01"
                              defaultValue={room.length_m ?? ""}
                              onBlur={(event) => roomMutation.mutate({ id: room.id, payload: { length_m: numberOrNull(event.currentTarget.value), source: "human" } })}
                            />
                          </TableCell>
                          <TableCell>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => roomMutation.mutate({ id: room.id, payload: { needs_review: false, source: room.source ?? "human" } })}
                            >
                              {room.needs_review ? "Validar" : "Revisada"}
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {!rooms.data?.length ? <p className="rounded-md border p-3 text-sm text-muted-foreground">Sin habitaciones detectadas.</p> : null}
                </section>

                <section className="space-y-2">
                  <h3 className="text-sm font-semibold">Cotas detectadas</h3>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Texto</TableHead>
                        <TableHead>Valor</TableHead>
                        <TableHead>Metros</TableHead>
                        <TableHead>Confianza</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(dimensions.data ?? []).map((dimension) => (
                        <TableRow key={dimension.id}>
                          <TableCell>{dimension.raw_text ?? "-"}</TableCell>
                          <TableCell>
                            {dimension.value ?? "-"} {dimension.unit ?? ""}
                          </TableCell>
                          <TableCell>{dimension.value_m?.toFixed(3) ?? "-"}</TableCell>
                          <TableCell>{dimension.confidence ? `${Math.round(dimension.confidence * 100)}%` : "-"}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {!dimensions.data?.length ? <p className="rounded-md border p-3 text-sm text-muted-foreground">Sin cotas textuales fiables.</p> : null}
                </section>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">No hay planos registrados todavía.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  )
}

function parseScaleRatio(value: string): number | null {
  const match = value.trim().match(/^1\s*[:/]\s*(\d+(?:[.,]\d+)?)$/)
  if (!match) return null
  const parsed = Number(match[1].replace(",", "."))
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

function numberOrNull(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}
