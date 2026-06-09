import {
  ChevronLeft,
  ChevronRight,
  Hand,
  Maximize2,
  Pencil,
  Ruler,
  type LucideIcon,
} from "lucide-react"

import { pageImageUrl } from "@/api/core"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { Plan } from "@/api/plans"

import {
  SVG_H,
  SVG_W,
  polygonAreaM2,
  type DraftDimension,
  type DraftRoom,
  type Point,
  type Tool,
} from "./usePlanAnnotation"

// ---------------------------------------------------------------------------
// Tool button
// ---------------------------------------------------------------------------
export function ToolButton({
  active,
  onClick,
  icon,
  label,
  hint,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
  hint?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={hint || label}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12px] font-medium transition-colors",
        active
          ? "border-[var(--accent)] bg-[var(--accent-faint)] text-[var(--accent)]"
          : "border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--text-primary)]",
      )}
    >
      {icon}
      {label}
    </button>
  )
}

export const TOOL_DEFS: Array<{
  id: Tool
  label: string
  icon: LucideIcon
  hint?: string
}> = [
  { id: "select", label: "Seleccionar", icon: Hand },
  {
    id: "room",
    label: "Habitación",
    icon: Pencil,
    hint: "Click vértices, doble-click cierra",
  },
  {
    id: "dimension",
    label: "Cota",
    icon: Ruler,
    hint: "Click 2 puntos",
  },
  {
    id: "scale",
    label: "Escala",
    icon: Maximize2,
    hint: "Click 2 puntos",
  },
]

// ---------------------------------------------------------------------------
// Canvas toolbar (tool selector + page navigator)
// ---------------------------------------------------------------------------
export function CanvasToolbar({
  tool,
  setTool,
  page,
  setPage,
}: {
  tool: Tool
  setTool: (t: Tool) => void
  page: number
  setPage: (updater: (p: number) => number) => void
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--bg-surface-2)]/40 px-3 py-2">
      <div className="flex items-center gap-1">
        {TOOL_DEFS.map((def) => (
          <ToolButton
            key={def.id}
            active={tool === def.id}
            onClick={() => setTool(def.id)}
            icon={<def.icon className="h-3.5 w-3.5" />}
            label={def.label}
            hint={def.hint}
          />
        ))}
      </div>
      <div className="flex items-center gap-1.5 text-[11.5px] text-[var(--text-muted)]">
        Página
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          onClick={() => setPage((p) => Math.max(1, p - 1))}
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </Button>
        <span className="w-6 text-center">{page}</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          onClick={() => setPage((p) => p + 1)}
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}

const fmt = (n: number | null | undefined, digits = 1) =>
  n == null || !isFinite(n) ? "—" : n.toFixed(digits)

// ---------------------------------------------------------------------------
// SVG canvas: page image + rooms + dimensions + in-progress drawings
// ---------------------------------------------------------------------------
export function PlanCanvas({
  documentId,
  page,
  tool,
  rooms,
  dimensions,
  polygonInProgress,
  draftDim,
  selectedId,
  setSelectedId,
  setTool,
  onCanvasClick,
  onCanvasDoubleClick,
  svgRef,
}: {
  documentId: number
  page: number
  tool: Tool
  rooms: DraftRoom[]
  dimensions: DraftDimension[]
  polygonInProgress: Point[]
  draftDim: DraftDimension | null
  selectedId: string | number | null
  setSelectedId: (id: string | number | null) => void
  setTool: (t: Tool) => void
  onCanvasClick: (e: React.MouseEvent<SVGSVGElement>) => void
  onCanvasDoubleClick: (e: React.MouseEvent<SVGSVGElement>) => void
  svgRef: React.RefObject<SVGSVGElement>
}) {
  return (
    <div className="relative min-h-0 flex-1 overflow-auto bg-[#1a1a1a] p-4">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${SVG_W} ${SVG_H}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-full w-full"
        style={{ cursor: tool === "select" ? "default" : "crosshair" }}
        onClick={onCanvasClick}
        onDoubleClick={onCanvasDoubleClick}
      >
        {/* Page image as a background layer */}
        <image
          href={pageImageUrl(documentId, page)}
          x="0"
          y="0"
          width={SVG_W}
          height={SVG_H}
          preserveAspectRatio="xMidYMid meet"
          opacity={0.85}
        />

        {/* Existing rooms */}
        {rooms.map((r) => (
          <g
            key={r.id}
            onClick={(e) => {
              e.stopPropagation()
              setSelectedId(r.id)
              setTool("select")
            }}
          >
            <polygon
              points={r.polygon?.map((p) => `${p.x},${p.y}`).join(" ")}
              fill={
                r.source?.startsWith("vision")
                  ? "rgba(59, 130, 246, 0.18)"
                  : "rgba(34, 197, 94, 0.18)"
              }
              stroke={
                selectedId === r.id
                  ? "#f59e0b"
                  : r.source?.startsWith("vision")
                    ? "#3b82f6"
                    : "#22c55e"
              }
              strokeWidth={selectedId === r.id ? 3 : 2}
            />
            {r.polygon && r.polygon.length > 0 && (
              <text
                x={r.polygon[0].x}
                y={r.polygon[0].y - 6}
                fill="white"
                fontSize="13"
                fontWeight="600"
                stroke="black"
                strokeWidth="0.4"
                paintOrder="stroke"
              >
                {r.name || "(sin nombre)"}{" "}
                {r.area_m2 != null ? `· ${fmt(r.area_m2, 1)} m²` : ""}
              </text>
            )}
          </g>
        ))}

        {/* In-progress polygon */}
        {polygonInProgress.length > 0 && (
          <polyline
            points={polygonInProgress.map((p) => `${p.x},${p.y}`).join(" ")}
            fill="rgba(245, 158, 11, 0.1)"
            stroke="#f59e0b"
            strokeWidth="2"
            strokeDasharray="4 3"
          />
        )}
        {polygonInProgress.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="3" fill="#f59e0b" />
        ))}

        {/* Existing dimensions */}
        {dimensions.map((d) =>
          d.start && d.end ? (
            <g key={d.id}>
              <line
                x1={d.start.x}
                y1={d.start.y}
                x2={d.end.x}
                y2={d.end.y}
                stroke="#a855f7"
                strokeWidth="2"
                strokeDasharray={d.raw_text === "escala" ? "2 4" : ""}
              />
              <text
                x={(d.start.x + d.end.x) / 2}
                y={(d.start.y + d.end.y) / 2 - 6}
                fill="white"
                fontSize="11"
                stroke="black"
                strokeWidth="0.4"
                paintOrder="stroke"
                textAnchor="middle"
              >
                {d.raw_text || `${d.value ?? "?"} ${d.unit ?? ""}`}
              </text>
            </g>
          ) : null,
        )}

        {/* In-progress dimension */}
        {draftDim && draftDim.start && (
          <line
            x1={draftDim.start.x}
            y1={draftDim.start.y}
            x2={draftDim.end?.x ?? draftDim.start.x}
            y2={draftDim.end?.y ?? draftDim.start.y}
            stroke="#a855f7"
            strokeWidth="2"
            strokeDasharray="4 2"
          />
        )}
      </svg>

      <CanvasHint tool={tool} polygonInProgress={polygonInProgress} draftDim={draftDim} />
    </div>
  )
}

function CanvasHint({
  tool,
  polygonInProgress,
  draftDim,
}: {
  tool: Tool
  polygonInProgress: Point[]
  draftDim: DraftDimension | null
}) {
  const text = (() => {
    if (tool === "room") {
      return polygonInProgress.length === 0
        ? "Click para añadir el primer vértice"
        : `${polygonInProgress.length} vértices · doble-click para cerrar`
    }
    if (tool === "dimension") {
      return draftDim?.start
        ? "Click para el segundo punto"
        : "Click para el primer punto de la cota"
    }
    if (tool === "scale") {
      return draftDim?.start
        ? "Click para el segundo punto de la escala"
        : "Click para el primer punto de la escala"
    }
    return null
  })()
  if (!text) return null
  return (
    <p className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-black/70 px-3 py-1 text-[11px] text-white">
      {text}
    </p>
  )
}

// ---------------------------------------------------------------------------
// Left sidebar: rooms + dimensions lists
// ---------------------------------------------------------------------------
export function AnnotationSidebar({
  rooms,
  dimensions,
  selectedId,
  setSelectedId,
}: {
  rooms: DraftRoom[]
  dimensions: DraftDimension[]
  selectedId: string | number | null
  setSelectedId: (id: string | number | null) => void
}) {
  return (
    <>
      <div className="border-b border-[var(--border)] px-3 py-2 text-[12px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
        Habitaciones ({rooms.length})
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {rooms.length === 0 ? (
          <p className="px-3 py-3 text-[12px] text-[var(--text-muted)]">
            Sin habitaciones. Pulsa <b>Habitación</b> abajo y dibuja un polígono.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {rooms.map((r) => (
              <li
                key={r.id}
                onClick={() => setSelectedId(r.id)}
                className={cn(
                  "cursor-pointer px-3 py-2 text-[12.5px] transition-colors",
                  selectedId === r.id
                    ? "bg-[var(--accent-faint)]"
                    : "hover:bg-[var(--bg-surface-2)]",
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{r.name || "(sin nombre)"}</span>
                  {r.source?.startsWith("vision") && (
                    <Badge variant="info" className="text-[10px]">
                      IA
                    </Badge>
                  )}
                </div>
                <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                  {r.area_m2 != null ? `${fmt(r.area_m2, 1)} m²` : "sin área"} ·{" "}
                  {r.polygon?.length ?? 0} vértices
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-[var(--border)] px-3 py-2 text-[12px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
        Cotas ({dimensions.length})
      </div>
      <div className="max-h-40 overflow-y-auto">
        {dimensions.length === 0 ? (
          <p className="px-3 py-2 text-[12px] text-[var(--text-muted)]">Sin cotas.</p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {dimensions.map((d) => (
              <li key={d.id} className="px-3 py-2 text-[12.5px]">
                <div className="font-medium">{d.raw_text || "(sin texto)"}</div>
                <div className="text-[11px] text-[var(--text-muted)]">
                  {d.value != null ? `${d.value} ${d.unit}` : "sin valor"} ·{" "}
                  {d.value_m != null ? `${fmt(d.value_m, 2)} m` : "—"}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Right editor panel: project name + scale + selected room + shortcuts
// ---------------------------------------------------------------------------
export function AnnotationEditor({
  plan,
  setProjectName,
  scaleDimension,
  scaleLengthM,
  setScaleLengthM,
  scaleRatio,
  selected,
  updateSelected,
  deleteSelected,
}: {
  plan: Plan | undefined
  setProjectName: (name: string) => void
  scaleDimension: DraftDimension | undefined
  scaleLengthM: string
  setScaleLengthM: (v: string) => void
  scaleRatio: number | null
  selected: DraftRoom | null
  updateSelected: (patch: Partial<DraftRoom>) => void
  deleteSelected: () => void
}) {
  return (
    <>
      <section>
        <h3 className="mb-1.5 text-[11.5px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
          Proyecto
        </h3>
        <input
          value={plan?.project_name ?? ""}
          placeholder="Nombre del proyecto"
          onChange={(e) => setProjectName(e.target.value)}
          className="h-8 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-2 text-[12.5px] focus:border-[var(--accent)] focus:outline-none"
        />
      </section>

      <ScaleEditor
        scaleDimension={scaleDimension}
        scaleLengthM={scaleLengthM}
        setScaleLengthM={setScaleLengthM}
        scaleRatio={scaleRatio}
      />

      <RoomEditor
        selected={selected}
        updateSelected={updateSelected}
        deleteSelected={deleteSelected}
        scaleRatio={scaleRatio}
      />

      <ShortcutsHint />
    </>
  )
}

function ScaleEditor({
  scaleDimension,
  scaleLengthM,
  setScaleLengthM,
  scaleRatio,
}: {
  scaleDimension: DraftDimension | undefined
  scaleLengthM: string
  setScaleLengthM: (v: string) => void
  scaleRatio: number | null
}) {
  return (
    <section>
      <h3 className="mb-1.5 text-[11.5px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
        Escala
      </h3>
      {scaleDimension ? (
        <div className="space-y-2">
          <p className="text-[11.5px] text-[var(--text-muted)]">
            Línea dibujada. Indica la longitud real:
          </p>
          <div className="flex gap-2">
            <input
              type="number"
              step="0.01"
              value={scaleLengthM}
              onChange={(e) => setScaleLengthM(e.target.value)}
              placeholder="metros"
              className="h-8 w-20 rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-2 text-[12.5px] focus:border-[var(--accent)] focus:outline-none"
            />
            <span className="self-center text-[12px] text-[var(--text-muted)]">m</span>
          </div>
          {scaleRatio != null && (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2 text-[11.5px] text-emerald-700 dark:text-emerald-300">
              1 px = <b>{fmt(scaleRatio * 100, 3)} cm</b> · escala 1:
              {fmt(1 / (scaleRatio * 100), 0)}
            </div>
          )}
        </div>
      ) : (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Selecciona la herramienta <b>Escala</b> y dibuja una línea sobre un elemento de
          longitud conocida.
        </p>
      )}
    </section>
  )
}

function RoomEditor({
  selected,
  updateSelected,
  deleteSelected,
  scaleRatio,
}: {
  selected: DraftRoom | null
  updateSelected: (patch: Partial<DraftRoom>) => void
  deleteSelected: () => void
  scaleRatio: number | null
}) {
  return (
    <section>
      <h3 className="mb-1.5 text-[11.5px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
        Habitación seleccionada
      </h3>
      {selected ? (
        <div className="space-y-2">
          <input
            value={selected.name}
            onChange={(e) => updateSelected({ name: e.target.value })}
            placeholder="Nombre"
            className="h-8 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-2 text-[12.5px] focus:border-[var(--accent)] focus:outline-none"
          />
          <div className="grid grid-cols-3 gap-2">
            <NumberField
              label="Ancho (m)"
              value={selected.width_m}
              onChange={(v) => updateSelected({ width_m: v })}
            />
            <NumberField
              label="Largo (m)"
              value={selected.length_m}
              onChange={(v) => updateSelected({ length_m: v })}
            />
            <NumberField
              label="Área (m²)"
              value={selected.area_m2}
              onChange={(v) => updateSelected({ area_m2: v })}
            />
          </div>
          {scaleRatio != null && selected.polygon && selected.polygon.length >= 3 && (
            <p className="text-[11px] text-[var(--text-muted)]">
              Área medida: {fmt(polygonAreaM2(selected.polygon, scaleRatio), 2)} m²
              (escala activa)
            </p>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={deleteSelected}
            className="gap-1.5 text-[var(--danger)]"
          >
            Eliminar
          </Button>
        </div>
      ) : (
        <p className="text-[11.5px] text-[var(--text-muted)]">
          Selecciona una habitación en la lista o en el plano.
        </p>
      )}
    </section>
  )
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string
  value: number | null
  onChange: (v: number | null) => void
}) {
  return (
    <div>
      <label className="text-[10.5px] text-[var(--text-muted)]">{label}</label>
      <input
        type="number"
        step="0.01"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="h-8 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-2 text-[12.5px] focus:border-[var(--accent)] focus:outline-none"
      />
    </div>
  )
}

function ShortcutsHint() {
  return (
    <section className="rounded-md border border-dashed border-[var(--border)] bg-[var(--bg-surface-2)]/40 p-2 text-[11px] text-[var(--text-muted)]">
      <p className="font-semibold uppercase tracking-wide">Atajos</p>
      <ul className="mt-1 space-y-0.5">
        <li>
          · <kbd className="rounded bg-[var(--bg-base)] px-1 font-mono text-[10px]">Esc</kbd>{" "}
          cancela el dibujo actual
        </li>
        <li>· Doble-click cierra un polígono</li>
        <li>· <b>Sugerir con IA</b> usa el vision model</li>
      </ul>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Page-wide breadcrumb
// ---------------------------------------------------------------------------
export function Breadcrumbs({ items }: { items: { label: string }[] }) {
  return (
    <nav className="border-b border-[var(--border)] bg-[var(--bg-surface)]/60 px-4 py-1.5 text-[12px] text-[var(--text-muted)] sm:px-6">
      <ol className="flex items-center gap-1.5">
        {items.map((it, i) => (
          <li key={i} className="flex items-center gap-1.5">
            {i > 0 && <span className="text-[var(--border-2)]">/</span>}
            <span>{it.label}</span>
          </li>
        ))}
      </ol>
    </nav>
  )
}
