import { useEffect, useMemo, useState } from "react"
import { Link, Navigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, ExternalLink, FlaskConical, Ruler, Save } from "lucide-react"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { useAuth } from "@/hooks/useAuth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

export function PlansPage() {
  const { user } = useAuth()

  // Solo admin y gestor pueden acceder
  if (!user || (user.role !== "admin" && user.role !== "gestor")) {
    return <Navigate to="/" replace />
  }
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [scaleText, setScaleText] = useState("")
  const [measurementLabel, setMeasurementLabel] = useState("")
  const [measurementValue, setMeasurementValue] = useState("")
  const [measurementOcrValue, setMeasurementOcrValue] = useState("")
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
  const measurements = useQuery({
    queryKey: ["plans", selectedPlan?.id, "measurements"],
    queryFn: () => api.planMeasurements(selectedPlan!.id),
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
  const measurementMutation = useMutation({
    mutationFn: () =>
      api.createPlanMeasurement(selectedPlan!.id, {
        label: measurementLabel.trim(),
        measurement_type: "distance",
        value_m: numberOrNull(measurementValue),
        ocr_value_m: numberOrNull(measurementOcrValue),
        points_json: [],
      }),
    onSuccess: () => {
      setMeasurementLabel("")
      setMeasurementValue("")
      setMeasurementOcrValue("")
      queryClient.invalidateQueries({ queryKey: ["plans", selectedPlan?.id, "measurements"] })
    },
  })

  useEffect(() => {
    if (selectedPlan) setScaleText(selectedPlan.scale_text ?? "")
  }, [selectedPlan])

  return (
    <>
      {/* Beta banner */}
      <div className="mb-4 flex items-start gap-3 rounded-lg border border-[var(--amber-light)] bg-[var(--amber-light)]/40 p-3">
        <FlaskConical className="mt-0.5 h-4 w-4 flex-shrink-0 text-[var(--amber)]" />
        <div>
          <p className="text-[13px] font-semibold text-[#92400E]">Funcionalidad en fase Beta</p>
          <p className="mt-0.5 text-[12px] text-[#92400E]/80">
            La extracción de planos está en desarrollo. Los datos de escala, habitaciones y cotas pueden no ser precisos.
            Verifica siempre las mediciones manualmente antes de usarlas en producción.
          </p>
        </div>
      </div>

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

                <section className="space-y-2">
                  <h3 className="text-sm font-semibold">Mediciones manuales</h3>
                  <form
                    className="grid gap-2 rounded-md border bg-slate-50 p-3 md:grid-cols-[1fr_120px_120px_auto]"
                    onSubmit={(event) => {
                      event.preventDefault()
                      if (measurementLabel.trim()) measurementMutation.mutate()
                    }}
                  >
                    <Input value={measurementLabel} onChange={(event) => setMeasurementLabel(event.target.value)} placeholder="Etiqueta, habitación o cota" />
                    <Input type="number" step="0.001" value={measurementValue} onChange={(event) => setMeasurementValue(event.target.value)} placeholder="Manual m" />
                    <Input type="number" step="0.001" value={measurementOcrValue} onChange={(event) => setMeasurementOcrValue(event.target.value)} placeholder="OCR m" />
                    <Button disabled={measurementMutation.isPending || !measurementLabel.trim()}>
                      <Save data-icon="inline-start" />
                      Guardar
                    </Button>
                  </form>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Etiqueta</TableHead>
                        <TableHead>Manual</TableHead>
                        <TableHead>OCR</TableHead>
                        <TableHead>Estado</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {(measurements.data ?? []).map((measurement) => (
                        <TableRow key={measurement.id}>
                          <TableCell>{measurement.label}</TableCell>
                          <TableCell>{measurement.value_m?.toFixed(3) ?? "-"}</TableCell>
                          <TableCell>{measurement.ocr_value_m?.toFixed(3) ?? "-"}</TableCell>
                          <TableCell>
                            <Badge variant={measurement.has_discrepancy ? "warning" : "success"}>
                              {measurement.has_discrepancy ? "discrepancia" : "cuadra"}
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {!measurements.data?.length ? <p className="rounded-md border p-3 text-sm text-muted-foreground">Sin mediciones manuales guardadas.</p> : null}
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
