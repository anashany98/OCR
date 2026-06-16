import { Ruler, Save } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

import { numberOrNull } from "./scales"
import type { PlansData } from "./usePlansPage"

/**
 * F8 - Plan editor column.
 *
 * The right-hand card on the plans page. Renders, in order:
 * - the manual scale input + save button
 * - the editable room table (name, m², width, length, needs review)
 * - the read-only detected dimensions table
 * - the manual measurements form + table
 *
 * The component is purely declarative: it receives the full
 * :class:`PlansData` object and binds to its state, queries and
 * mutations. The "no plan selected" empty state is rendered by
 * the parent ``PlansPage`` so the page shell owns the layout
 * boundary.
 */
export function PlanEditor({ data }: { data: PlansData }) {
  const plan = data.data.selectedPlan
  if (!plan) return null
  return (
    <div className="space-y-4">
      <ScaleSection data={data} />
      <RoomsSection data={data} />
      <DimensionsSection data={data} />
      <MeasurementsSection data={data} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// ScaleSection
// ---------------------------------------------------------------------------
function ScaleSection({ data }: { data: PlansData }) {
  const { state, mutations } = data
  return (
    <div className="grid gap-2 rounded-md border p-3">
      <label className="text-xs font-medium text-muted-foreground">Escala manual</label>
      <div className="flex gap-2">
        <Input
          onChange={(event) => state.setScaleText(event.target.value)}
          placeholder="1:50"
          value={state.scaleText}
        />
        <Button
          disabled={mutations.scale.isPending}
          onClick={() => mutations.scale.mutate()}
        >
          <Save data-icon="inline-start" />
          Guardar
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Sin escala válida no se convierten geometrías de píxeles a metros. Las superficies OCR se conservan como texto fuente.
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// RoomsSection
// ---------------------------------------------------------------------------
function RoomsSection({ data }: { data: PlansData }) {
  const { queries, mutations } = data
  const rooms = queries.rooms.data ?? []
  return (
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
          {rooms.map((room) => (
            <TableRow key={room.id}>
              <TableCell>
                <Input
                  defaultValue={room.name ?? ""}
                  onBlur={(event) =>
                    mutations.room.mutate({
                      id: room.id,
                      payload: { name: event.currentTarget.value || null },
                    })
                  }
                />
              </TableCell>
              <TableCell>
                <Input
                  type="number"
                  step="0.01"
                  defaultValue={room.area_m2 ?? ""}
                  onBlur={(event) =>
                    mutations.room.mutate({
                      id: room.id,
                      payload: { area_m2: numberOrNull(event.currentTarget.value) },
                    })
                  }
                />
              </TableCell>
              <TableCell>
                <Input
                  type="number"
                  step="0.01"
                  defaultValue={room.width_m ?? ""}
                  onBlur={(event) =>
                    mutations.room.mutate({
                      id: room.id,
                      payload: {
                        width_m: numberOrNull(event.currentTarget.value),
                        source: "human",
                      },
                    })
                  }
                />
              </TableCell>
              <TableCell>
                <Input
                  type="number"
                  step="0.01"
                  defaultValue={room.length_m ?? ""}
                  onBlur={(event) =>
                    mutations.room.mutate({
                      id: room.id,
                      payload: {
                        length_m: numberOrNull(event.currentTarget.value),
                        source: "human",
                      },
                    })
                  }
                />
              </TableCell>
              <TableCell>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    mutations.room.mutate({
                      id: room.id,
                      payload: { needs_review: false, source: room.source ?? "human" },
                    })
                  }
                >
                  {room.needs_review ? "Validar" : "Revisada"}
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {!rooms.length ? (
        <p className="rounded-md border p-3 text-sm text-muted-foreground">
          Sin habitaciones detectadas.
        </p>
      ) : null}
    </section>
  )
}

// ---------------------------------------------------------------------------
// DimensionsSection
// ---------------------------------------------------------------------------
function DimensionsSection({ data }: { data: PlansData }) {
  const dimensions = data.queries.dimensions.data ?? []
  return (
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
          {dimensions.map((dimension) => (
            <TableRow key={dimension.id}>
              <TableCell>{dimension.raw_text ?? "-"}</TableCell>
              <TableCell>
                {dimension.value ?? "-"} {dimension.unit ?? ""}
              </TableCell>
              <TableCell>{dimension.value_m?.toFixed(3) ?? "-"}</TableCell>
              <TableCell>
                {dimension.confidence ? `${Math.round(dimension.confidence * 100)}%` : "-"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {!dimensions.length ? (
        <p className="rounded-md border p-3 text-sm text-muted-foreground">
          Sin cotas textuales fiables.
        </p>
      ) : null}
    </section>
  )
}

// ---------------------------------------------------------------------------
// MeasurementsSection
// ---------------------------------------------------------------------------
function MeasurementsSection({ data }: { data: PlansData }) {
  const { state, queries, mutations } = data
  const measurements = queries.measurements.data ?? []
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">Mediciones manuales</h3>
      <form
        className="grid gap-2 rounded-md border bg-slate-50 p-3 md:grid-cols-[1fr_120px_120px_auto]"
        onSubmit={(event) => {
          event.preventDefault()
          if (state.measurementLabel.trim()) mutations.measurement.mutate()
        }}
      >
        <Input
          onChange={(event) => state.setMeasurementLabel(event.target.value)}
          placeholder="Etiqueta, habitación o cota"
          value={state.measurementLabel}
        />
        <Input
          type="number"
          step="0.001"
          onChange={(event) => state.setMeasurementValue(event.target.value)}
          placeholder="Manual m"
          value={state.measurementValue}
        />
        <Input
          type="number"
          step="0.001"
          onChange={(event) => state.setMeasurementOcrValue(event.target.value)}
          placeholder="OCR m"
          value={state.measurementOcrValue}
        />
        <Button disabled={mutations.measurement.isPending || !state.measurementLabel.trim()}>
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
          {measurements.map((measurement) => (
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
      {!measurements.length ? (
        <p className="rounded-md border p-3 text-sm text-muted-foreground">
          Sin mediciones manuales guardadas.
        </p>
      ) : null}
    </section>
  )
}
