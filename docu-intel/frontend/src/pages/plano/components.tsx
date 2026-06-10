import {
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
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
import type { Plan, PlanSymbol } from "@/api/plans"

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
  symbolOverlay,
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
  /** P2 — YOLO symbol overlay, rendered behind the in-progress
   * drawings so the user's current room/dimension/scale work is
   * never hidden by a detection. Pass ``null`` to disable. */
  symbolOverlay?: React.ReactNode
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

        {/* P2 — YOLO symbol overlay. Drawn between the existing
            annotations and the in-progress drawings so the user's
            current selection is never hidden by a detection box. */}
        {symbolOverlay}

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
// Left sidebar: rooms + dimensions lists + P2 symbol legend
// ---------------------------------------------------------------------------
export function AnnotationSidebar({
  rooms,
  dimensions,
  selectedId,
  setSelectedId,
  symbolLegend,
}: {
  rooms: DraftRoom[]
  dimensions: DraftDimension[]
  selectedId: string | number | null
  setSelectedId: (id: string | number | null) => void
  /** P2 — optional YOLO symbol legend. When present, it renders at
   * the bottom of the sidebar below the dimensions list. */
  symbolLegend?: React.ReactNode
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

      {symbolLegend}
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
// P2 — Symbol overlay
// ---------------------------------------------------------------------------
//
// SVG layer that draws the YOLO bounding boxes on top of the plan
// image. The component takes a list of already-filtered symbols
// (caller decides what page / classes are visible) and renders one
// ``<g>`` per detection. Clicking a box selects it (a no-op for now
// — the legend is the main interaction surface).
//
// The component does not manage filters; it just paints. The
// ``usePlanSymbols`` hook is the source of truth.
//
// We rely on the plan image being 1200x850 (matching the
// ``SVG_W``/``SVG_H`` constants). Bounding boxes are in the same
// coordinate system, so the overlay does not need to transform.
//
// Why we don't use HTML overlays: the SVG canvas is zoom/pan-aware
// and the boxes have to scale with it. Keeping the overlay as SVG
// children means zoom/pan comes for free.

export function SymbolOverlay({
  symbols,
  colorForClass,
}: {
  symbols: PlanSymbol[]
  colorForClass: (cls: string) => string
}) {
  if (symbols.length === 0) return null
  return (
    <g pointerEvents="none" data-testid="symbol-overlay">
      {symbols.map((sym) => {
        // Skip boxes that have no coords; they cannot be drawn.
        if (
          sym.bbox_x1 == null ||
          sym.bbox_y1 == null ||
          sym.bbox_x2 == null ||
          sym.bbox_y2 == null
        ) {
          return null
        }
        const x = Math.min(sym.bbox_x1, sym.bbox_x2)
        const y = Math.min(sym.bbox_y1, sym.bbox_y2)
        const w = Math.abs(sym.bbox_x2 - sym.bbox_x1)
        const h = Math.abs(sym.bbox_y2 - sym.bbox_y1)
        const color = colorForClass(sym.symbol_class)
        return (
          <g key={sym.id} data-symbol-class={sym.symbol_class}>
            <rect
              x={x}
              y={y}
              width={w}
              height={h}
              fill={color}
              fillOpacity={0.10}
              stroke={color}
              strokeOpacity={0.85}
              strokeWidth={1.5}
            />
            <text
              x={x}
              y={y - 3}
              fill={color}
              fontSize="9"
              fontWeight="600"
              stroke="black"
              strokeOpacity={0.55}
              strokeWidth={0.3}
              paintOrder="stroke"
            >
              {sym.symbol_class}
            </text>
          </g>
        )
      })}
    </g>
  )
}

// ---------------------------------------------------------------------------
// P2 — Symbol legend (side panel)
// ---------------------------------------------------------------------------
//
// Compact class list with per-class count, a visibility toggle for
// the overlay as a whole, and per-class show/hide checkboxes. Renders
// a friendly empty state when the detector has not run yet (the
// ``summary`` query returns an empty ``counts`` object).
//
// The legend is intentionally light: a class shows a coloured swatch
// (matching the overlay), the humanised class name, the count, and
// a checkbox. No editing, no drill-down — those would be a separate
// "Symbol details" panel.

export function SymbolLegend({
  visible,
  onToggleVisible,
  total,
  classes,
  counts,
  activeClasses,
  onToggleClass,
  onEnableAll,
  onDisableAll,
  sourceModel,
  isLoading,
}: {
  visible: boolean
  onToggleVisible: () => void
  total: number
  classes: string[]
  counts: Record<string, number>
  activeClasses: Set<string> | null
  onToggleClass: (cls: string) => void
  onEnableAll: () => void
  onDisableAll: () => void
  sourceModel: string | null
  isLoading: boolean
}) {
  return (
    <section
      className="flex flex-col gap-2 border-t border-[var(--border)] bg-[var(--bg-surface-2)]/40 p-2"
      data-testid="symbol-legend"
    >
      <header className="flex items-center justify-between">
        <h3 className="text-[11.5px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
          Símbolos detectados ({total})
        </h3>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 gap-1 px-1.5 text-[11px]"
          onClick={onToggleVisible}
          title={visible ? "Ocultar símbolos en el plano" : "Mostrar símbolos en el plano"}
          aria-label={visible ? "Ocultar símbolos" : "Mostrar símbolos"}
        >
          {visible ? (
            <>
              <Eye className="h-3 w-3" /> Visibles
            </>
          ) : (
            <>
              <EyeOff className="h-3 w-3" /> Ocultos
            </>
          )}
        </Button>
      </header>

      {isLoading ? (
        <p className="px-1 py-1 text-[11.5px] text-[var(--text-muted)]">
          Cargando detecciones…
        </p>
      ) : classes.length === 0 ? (
        <p className="px-1 py-1 text-[11.5px] text-[var(--text-muted)]">
          No se han detectado símbolos todavía. Si el plano se acaba de
          procesar, espera unos segundos y recarga.
        </p>
      ) : (
        <>
          <div className="flex items-center gap-1.5 text-[10.5px] text-[var(--text-muted)]">
            <button
              type="button"
              onClick={onEnableAll}
              className="rounded border border-[var(--border)] bg-[var(--bg-surface)] px-1.5 py-0.5 hover:border-[var(--accent)]"
            >
              Todas
            </button>
            <button
              type="button"
              onClick={onDisableAll}
              className="rounded border border-[var(--border)] bg-[var(--bg-surface)] px-1.5 py-0.5 hover:border-[var(--accent)]"
            >
              Ninguna
            </button>
            {sourceModel && (
              <span className="ml-auto truncate font-mono text-[10px] opacity-70" title={sourceModel}>
                {sourceModel}
              </span>
            )}
          </div>

          <ul className="max-h-40 space-y-0.5 overflow-y-auto pr-1">
            {classes.map((cls) => {
              const isActive = activeClasses ? activeClasses.has(cls) : true
              return (
                <li
                  key={cls}
                  className={cn(
                    "flex items-center justify-between gap-1.5 rounded px-1.5 py-0.5 text-[11.5px] transition-colors",
                    isActive
                      ? "bg-[var(--bg-surface)] text-[var(--text-primary)]"
                      : "bg-transparent text-[var(--text-muted)]",
                  )}
                >
                  <label className="flex flex-1 cursor-pointer items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={isActive}
                      onChange={() => onToggleClass(cls)}
                      className="h-3 w-3 cursor-pointer accent-[var(--accent)]"
                      aria-label={`Mostrar ${cls}`}
                    />
                    <span
                      className="inline-block h-2.5 w-2.5 flex-none rounded-sm border border-black/20"
                      style={{ backgroundColor: colorForLegend(cls) }}
                      aria-hidden="true"
                    />
                    <span className="truncate" title={cls}>
                      {humaniseLegend(cls)}
                    </span>
                  </label>
                  <Badge variant="secondary" className="px-1.5 py-0 text-[10.5px]">
                    {counts[cls] ?? 0}
                  </Badge>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </section>
  )
}

// Helpers used only by the legend. Kept private to this module so
// the canvas and the legend stay in sync (same colour, same label).

/**
 * Public, stable color picker for any symbol class. Used by the
 * page composition layer (and tests) to keep the legend swatch
 * and the canvas overlay aligned without reaching into module
 * internals.
 */
export function colorForSymbolClass(cls: string): string {
  // Same hashing scheme as the overlay so the swatch in the legend
  // matches the box on the canvas.
  let h = 0
  for (let i = 0; i < cls.length; i++) {
    h = (h * 31 + cls.charCodeAt(i)) & 0xffffffff
  }
  const hue = Math.abs(h % 360)
  return `hsl(${hue}, 70%, 55%)`
}

function humaniseLegend(cls: string): string {
  if (!cls) return cls
  return cls
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function colorForLegend(cls: string): string {
  // Same hashing scheme as the overlay so the swatch in the legend
  // matches the box on the canvas. We import nothing from the hook
  // to keep the legend renderable in isolation.
  return colorForSymbolClass(cls)
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
