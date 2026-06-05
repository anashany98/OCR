import {
  FormEvent,
  KeyboardEvent,
  MouseEvent as ReactMouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowLeft,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Eraser,
  Hand,
  Loader2,
  MapPin,
  Maximize2,
  Pencil,
  Plus,
  Ruler,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react"

import { api } from "@/api/client"
import { plansApi, type Plan, type PlanDimension, type PlanRoom } from "@/api/plans"
import { pageImageUrl } from "@/api/core"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import { notify } from "@/lib/toast"

const fmt = (n: number | null | undefined, digits = 1) =>
  n == null || !isFinite(n) ? "—" : n.toFixed(digits)

type Tool = "select" | "room" | "dimension" | "scale"

type Point = { x: number; y: number }

// Local copy of a room being edited. We use the same id+shape as PlanRoom
// for the working set so save semantics are simple.
type DraftRoom = {
  id: number | string // number = server id, "draft-N" = new
  name: string
  area_m2: number | null
  width_m: number | null
  length_m: number | null
  polygon: Point[] | null
  source: string | null
  confidence: number | null
  needs_review: boolean
  page_number: number | null
}

type DraftDimension = {
  id: number | string
  raw_text: string
  value: number | null
  unit: string
  value_m: number | null
  page_number: number | null
  start: Point | null
  end: Point | null
}

const SVG_W = 1200 // nominal coordinate system; we scale by image natural size
const SVG_H = 850

export function PlanoAnnotationPage() {
  const { id } = useParams<{ id: string }>()
  const documentId = Number(id)
  const navigate = useNavigate()
  const qc = useQueryClient()

  // --------------------------------------------------------------------
  // Data fetching
  // --------------------------------------------------------------------
  const plansList = useQuery({
    queryKey: ["plans-list"],
    queryFn: () => plansApi.list(200),
    staleTime: 60_000,
  })
  const plan = useMemo<Plan | undefined>(
    () => plansList.data?.find((p) => p.document_id === documentId),
    [plansList.data, documentId],
  )
  const planId = plan?.id

  const roomsQuery = useQuery({
    queryKey: ["plan-rooms", planId],
    queryFn: () => plansApi.getRooms(planId!),
    enabled: !!planId,
  })
  const dimensionsQuery = useQuery({
    queryKey: ["plan-dimensions", planId],
    queryFn: () => plansApi.getDimensions(planId!),
    enabled: !!planId,
  })

  // --------------------------------------------------------------------
  // Page selector (planos can be multi-page PDFs)
  // --------------------------------------------------------------------
  const [page, setPage] = useState(1)
  const pageCount = plan ? Math.max(1, 1) : 1
  // (We don't have a page count endpoint; we let the user pick freely.)

  // --------------------------------------------------------------------
  // Local working state
  // --------------------------------------------------------------------
  const [rooms, setRooms] = useState<DraftRoom[]>([])
  const [dimensions, setDimensions] = useState<DraftDimension[]>([])
  const [tool, setTool] = useState<Tool>("select")
  const [selectedId, setSelectedId] = useState<string | number | null>(null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [polygonInProgress, setPolygonInProgress] = useState<Point[]>([])
  const [draftDim, setDraftDim] = useState<DraftDimension | null>(null)

  // Hydrate from server
  useEffect(() => {
    if (!roomsQuery.data) return
    setRooms(
      roomsQuery.data.map((r) => ({
        id: r.id,
        name: r.name ?? "",
        area_m2: r.area_m2,
        width_m: r.width_m,
        length_m: r.length_m,
        polygon: r.polygon_json?.points ?? null,
        source: r.source,
        confidence: r.confidence,
        needs_review: r.needs_review,
        page_number: null,
      })),
    )
    setDirty(false)
  }, [roomsQuery.data])

  useEffect(() => {
    if (!dimensionsQuery.data) return
    setDimensions(
      dimensionsQuery.data.map((d) => ({
        id: d.id,
        raw_text: d.raw_text ?? "",
        value: d.value,
        unit: d.unit ?? "m",
        value_m: d.value_m,
        page_number: d.page_number ?? null,
        start: d.bbox_x1 != null && d.bbox_y1 != null ? { x: d.bbox_x1, y: d.bbox_y1 } : null,
        end: d.bbox_x2 != null && d.bbox_y2 != null ? { x: d.bbox_x2, y: d.bbox_y2 } : null,
      })),
    )
  }, [dimensionsQuery.data])

  // --------------------------------------------------------------------
  // Vision-assisted suggestions
  // --------------------------------------------------------------------
  const [suggesting, setSuggesting] = useState(false)
  const suggest = useCallback(async () => {
    if (!planId) return
    setSuggesting(true)
    try {
      const out = await plansApi.suggestRooms(planId, page)
      // Merge: for each suggestion, create a draft room centred on the
      // bbox (top-left + width/height).
      const w = out.rooms.length ? out.rooms[0].bbox[2] - out.rooms[0].bbox[0] : 100
      const h = out.rooms.length ? out.rooms[0].bbox[3] - out.rooms[0].bbox[1] : 100
      const newDrafts: DraftRoom[] = out.rooms.map((s) => ({
        id: `vision-${crypto.randomUUID()}`,
        name: s.name,
        area_m2: null,
        width_m: null,
        length_m: null,
        polygon: [
          { x: s.bbox[0], y: s.bbox[1] },
          { x: s.bbox[0] + w, y: s.bbox[1] },
          { x: s.bbox[0] + w, y: s.bbox[1] + h },
          { x: s.bbox[0], y: s.bbox[1] + h },
        ],
        source: `vision:${s.confidence ?? 0.6}`,
        confidence: s.confidence,
        needs_review: true,
        page_number: page,
      }))
      setRooms((cur) => [...cur, ...newDrafts])
      setDirty(true)
      notify.success(
        `${newDrafts.length} sugerencias listas`,
        "Revisa los nombres y polígonos. Las habitaciones marcadas en azul son sugerencias de la IA.",
      )
    } catch (err) {
      notify.error(err as Error, "No se pudieron obtener sugerencias")
    } finally {
      setSuggesting(false)
    }
  }, [planId, page])

  // --------------------------------------------------------------------
  // Canvas interaction
  // --------------------------------------------------------------------
  const svgRef = useRef<SVGSVGElement | null>(null)
  const toSvgCoords = useCallback((e: ReactMouseEvent | MouseEvent): Point | null => {
    const svg = svgRef.current
    if (!svg) return null
    const rect = svg.getBoundingClientRect()
    const x = ((e.clientX - rect.left) / rect.width) * SVG_W
    const y = ((e.clientY - rect.top) / rect.height) * SVG_H
    return { x, y }
  }, [])

  const hitRoom = useCallback(
    (p: Point): DraftRoom | null => {
      for (const r of rooms) {
        if (!r.polygon || r.polygon.length < 3) continue
        // Ray cast
        let inside = false
        for (let i = 0, j = r.polygon.length - 1; i < r.polygon.length; j = i++) {
          const xi = r.polygon[i].x, yi = r.polygon[i].y
          const xj = r.polygon[j].x, yj = r.polygon[j].y
          const intersect = (yi > p.y) !== (yj > p.y) &&
            p.x < ((xj - xi) * (p.y - yi)) / (yj - yi + 1e-9) + xi
          if (intersect) inside = !inside
        }
        if (inside) return r
      }
      return null
    },
    [rooms],
  )

  const onCanvasClick = useCallback(
    (e: ReactMouseEvent<SVGSVGElement>) => {
      const p = toSvgCoords(e)
      if (!p) return

      if (tool === "select") {
        const hit = hitRoom(p)
        if (hit) {
          setSelectedId(hit.id)
        } else {
          setSelectedId(null)
        }
        return
      }

      if (tool === "room") {
        // Add a vertex; double-click closes the polygon.
        setPolygonInProgress((cur) => [...cur, p])
        setDirty(true)
        return
      }

      if (tool === "dimension") {
        if (!draftDim) {
          setDraftDim({
            id: `draft-d-${Date.now()}`,
            raw_text: "",
            value: null,
            unit: "m",
            value_m: null,
            page_number: page,
            start: p,
            end: null,
          })
        } else if (draftDim && !draftDim.end) {
          const completed: DraftDimension = { ...draftDim, end: p }
          setDimensions((cur) => [...cur, completed])
          setDraftDim(null)
          setTool("select")
          setDirty(true)
        }
        return
      }

      if (tool === "scale") {
        if (!draftDim) {
          setDraftDim({
            id: `scale-${Date.now()}`,
            raw_text: "escala",
            value: null,
            unit: "m",
            value_m: null,
            page_number: page,
            start: p,
            end: null,
          })
        } else {
          const completed: DraftDimension = { ...draftDim, end: p }
          setDimensions((cur) => [...cur, completed])
          setDraftDim(null)
          setTool("select")
          setDirty(true)
        }
        return
      }
    },
    [tool, toSvgCoords, hitRoom, draftDim, page],
  )

  const onCanvasDoubleClick = useCallback(() => {
    if (tool === "room" && polygonInProgress.length >= 3) {
      const newRoom: DraftRoom = {
        id: `draft-${Date.now()}`,
        name: "Nueva habitación",
        area_m2: null,
        width_m: null,
        length_m: null,
        polygon: polygonInProgress,
        source: "manual",
        confidence: 1.0,
        needs_review: false,
        page_number: page,
      }
      setRooms((cur) => [...cur, newRoom])
      setPolygonInProgress([])
      setSelectedId(newRoom.id)
      setTool("select")
      setDirty(true)
    }
  }, [tool, polygonInProgress, page])

  // Cancel polygon on Escape
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") {
        setPolygonInProgress([])
        setDraftDim(null)
        setTool("select")
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  // --------------------------------------------------------------------
  // Selection
  // --------------------------------------------------------------------
  const selected = useMemo(() => {
    if (selectedId == null) return null
    return rooms.find((r) => r.id === selectedId) ?? null
  }, [rooms, selectedId])

  const updateSelected = useCallback(
    (patch: Partial<DraftRoom>) => {
      if (selectedId == null) return
      setRooms((cur) =>
        cur.map((r) => (r.id === selectedId ? { ...r, ...patch } : r)),
      )
      setDirty(true)
    },
    [selectedId],
  )

  const deleteSelected = useCallback(() => {
    if (selectedId == null) return
    setRooms((cur) => cur.filter((r) => r.id !== selectedId))
    setSelectedId(null)
    setDirty(true)
  }, [selectedId])

  // --------------------------------------------------------------------
  // Scale: a "scale" dimension links pixels to metres. The user draws a
  // line and tells us the real-world length; we compute the scale factor
  // and store it on the plan.
  // --------------------------------------------------------------------
  const [scaleLengthM, setScaleLengthM] = useState<string>("")
  const scaleDimension = dimensions.find((d) => d.raw_text === "escala")
  const computeScale = useCallback(() => {
    if (!scaleDimension || !scaleDimension.start || !scaleDimension.end) return null
    const dx = scaleDimension.end.x - scaleDimension.start.x
    const dy = scaleDimension.end.y - scaleDimension.start.y
    const pxLen = Math.sqrt(dx * dx + dy * dy)
    const m = Number(scaleLengthM)
    if (!isFinite(m) || m <= 0 || pxLen <= 0) return null
    return m / pxLen
  }, [scaleDimension, scaleLengthM])
  const scaleRatio = computeScale()

  // --------------------------------------------------------------------
  // Save
  // --------------------------------------------------------------------
  const onSave = useCallback(async () => {
    if (!planId) return
    setSaving(true)
    try {
      // Build the bulk payload. Only include sections the user touched
      // (so we don't clobber server-side state on the other fields).
      const payload: Parameters<typeof plansApi.bulkUpdate>[1] = {
        rooms: rooms.map((r) => ({
          // id is a string for new/draft rooms, drop it
          name: r.name,
          area_m2: r.area_m2,
          width_m: r.width_m,
          length_m: r.length_m,
          polygon_json: r.polygon ? { points: r.polygon } : null,
          page_number: r.page_number ?? page,
          source: r.source ?? "manual",
          confidence: r.confidence ?? 1.0,
          needs_review: r.needs_review,
        })),
        dimensions: dimensions.map((d) => ({
          raw_text: d.raw_text,
          value: d.value,
          unit: d.unit,
          value_m: d.value_m,
          page_number: d.page_number ?? page,
          bbox_x1: d.start?.x ?? null,
          bbox_y1: d.start?.y ?? null,
          bbox_x2: d.end?.x ?? null,
          bbox_y2: d.end?.y ?? null,
          confidence: 1.0,
        })),
        scale_text: plan?.scale_text ?? null,
        scale_ratio: scaleRatio ?? plan?.scale_ratio ?? null,
        unit: "m",
        has_valid_scale: scaleRatio != null ? true : (plan?.has_valid_scale ?? false),
        project_name: plan?.project_name ?? null,
      }
      await plansApi.bulkUpdate(planId, payload)
      notify.success("Plano guardado", "Las anotaciones se han guardado.")
      setDirty(false)
      qc.invalidateQueries({ queryKey: ["plan-rooms", planId] })
      qc.invalidateQueries({ queryKey: ["plan-dimensions", planId] })
    } catch (err) {
      notify.error(err as Error, "No se pudo guardar el plano")
    } finally {
      setSaving(false)
    }
  }, [planId, plan, rooms, dimensions, scaleRatio, page, qc])

  // --------------------------------------------------------------------
  // Render
  // --------------------------------------------------------------------
  const doc = plansList.data?.find((p) => p.document_id === documentId)
  const fileName = doc ? "" : ""

  if (!plan && plansList.isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Cargando plano...
      </div>
    )
  }
  if (!plan) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <p className="text-sm text-muted-foreground">
          Este documento no está clasificado como plano o no tiene un Plan asociado.
        </p>
        <Link
          to={`/documents/${documentId}`}
          className="text-[12px] text-[var(--accent)] underline"
        >
          Volver al documento
        </Link>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Breadcrumbs items={[{ label: "Anotar plano" }]} />

      {/* Top bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--bg-surface)] px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/documents/${documentId}`)}
            className="gap-1.5"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Volver
          </Button>
          <div className="ml-1 flex flex-col">
            <span className="text-[12.5px] font-semibold text-[var(--text-primary)]">
              Plano #{plan.id} · doc #{plan.document_id}
            </span>
            <span className="text-[11px] text-[var(--text-muted)]">
              {plan.project_name || "Sin nombre de proyecto"} ·{" "}
              {plan.has_valid_scale ? `escala 1:${plan.scale_ratio}` : "sin escala"}
              {dirty ? " · cambios sin guardar" : ""}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={suggest}
            disabled={suggesting}
            className="gap-1.5"
          >
            {suggesting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Sugerir con IA
          </Button>
          <Button
            size="sm"
            onClick={onSave}
            disabled={saving || !dirty}
            className="gap-1.5"
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            Guardar
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 sm:p-4 lg:grid-cols-[280px_minmax(0,1fr)_300px]">
        {/* LEFT: list of rooms + dimensions */}
        <Card className="flex min-h-0 flex-col overflow-hidden">
          <CardContent className="flex min-h-0 flex-col gap-0 p-0">
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
                          <Badge variant="info" className="text-[10px]">IA</Badge>
                        )}
                      </div>
                      <div className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                        {r.area_m2 != null ? `${fmt(r.area_m2, 1)} m²` : "sin área"} · {r.polygon?.length ?? 0} vértices
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
                <p className="px-3 py-2 text-[12px] text-[var(--text-muted)]">
                  Sin cotas.
                </p>
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
          </CardContent>
        </Card>

        {/* CENTER: canvas */}
        <Card className="flex min-h-0 flex-col overflow-hidden">
          <CardContent className="flex min-h-0 flex-1 flex-col gap-0 p-0">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--bg-surface-2)]/40 px-3 py-2">
              <div className="flex items-center gap-1">
                <ToolButton active={tool === "select"} onClick={() => setTool("select")} icon={<Hand className="h-3.5 w-3.5" />} label="Seleccionar" />
                <ToolButton active={tool === "room"} onClick={() => setTool("room")} icon={<Pencil className="h-3.5 w-3.5" />} label="Habitación" hint="Click vértices, doble-click cierra" />
                <ToolButton active={tool === "dimension"} onClick={() => setTool("dimension")} icon={<Ruler className="h-3.5 w-3.5" />} label="Cota" hint="Click 2 puntos" />
                <ToolButton active={tool === "scale"} onClick={() => setTool("scale")} icon={<Maximize2 className="h-3.5 w-3.5" />} label="Escala" hint="Click 2 puntos" />
              </div>
              <div className="flex items-center gap-1.5 text-[11.5px] text-[var(--text-muted)]">
                Página
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => setPage((p) => Math.max(1, p - 1))}>
                  <ChevronLeft className="h-3.5 w-3.5" />
                </Button>
                <span className="w-6 text-center">{page}</span>
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => setPage((p) => p + 1)}>
                  <ChevronRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>

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
                {/* The page image as a background layer */}
                <image
                  href={pageImageUrl(plan.document_id, page)}
                  x="0"
                  y="0"
                  width={SVG_W}
                  height={SVG_H}
                  preserveAspectRatio="xMidYMid meet"
                  opacity={0.85}
                />

                {/* Existing rooms */}
                {rooms.map((r) => (
                  <g key={r.id} onClick={(e) => { e.stopPropagation(); setSelectedId(r.id); setTool("select") }}>
                    <polygon
                      points={r.polygon?.map((p) => `${p.x},${p.y}`).join(" ")}
                      fill={
                        r.source?.startsWith("vision")
                          ? "rgba(59, 130, 246, 0.18)"
                          : "rgba(34, 197, 94, 0.18)"
                      }
                      stroke={selectedId === r.id ? "#f59e0b" : r.source?.startsWith("vision") ? "#3b82f6" : "#22c55e"}
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

              {tool === "room" && (
                <p className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-black/70 px-3 py-1 text-[11px] text-white">
                  {polygonInProgress.length === 0
                    ? "Click para añadir el primer vértice"
                    : `${polygonInProgress.length} vértices · doble-click para cerrar`}
                </p>
              )}
              {tool === "dimension" && (
                <p className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-black/70 px-3 py-1 text-[11px] text-white">
                  {draftDim?.start ? "Click para el segundo punto" : "Click para el primer punto de la cota"}
                </p>
              )}
              {tool === "scale" && (
                <p className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full bg-black/70 px-3 py-1 text-[11px] text-white">
                  {draftDim?.start
                    ? "Click para el segundo punto de la escala"
                    : "Click para el primer punto de la escala"}
                </p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* RIGHT: editor */}
        <Card className="flex min-h-0 flex-col overflow-hidden">
          <CardContent className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
            {/* Project name + scale */}
            <section>
              <h3 className="mb-1.5 text-[11.5px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                Proyecto
              </h3>
              <input
                value={plan.project_name ?? ""}
                placeholder="Nombre del proyecto"
                onChange={(e) => {
                  // Optimistic local update; the bulk save persists it.
                  if (plansList.data) {
                    const idx = plansList.data.findIndex((p) => p.id === plan.id)
                    if (idx >= 0) plansList.data[idx].project_name = e.target.value
                  }
                  setDirty(true)
                }}
                className="h-8 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-2 text-[12.5px] focus:border-[var(--accent)] focus:outline-none"
              />
            </section>

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
                      <CheckCircle2 className="mr-1 inline h-3.5 w-3.5" />
                      1 px = <b>{fmt(scaleRatio * 100, 3)} cm</b> · escala 1:{fmt(1 / (scaleRatio * 100), 0)}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  Selecciona la herramienta <b>Escala</b> y dibuja una línea sobre un elemento de longitud conocida.
                </p>
              )}
            </section>

            {/* Selected room editor */}
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
                    <div>
                      <label className="text-[10.5px] text-[var(--text-muted)]">Ancho (m)</label>
                      <input
                        type="number"
                        step="0.01"
                        value={selected.width_m ?? ""}
                        onChange={(e) =>
                          updateSelected({ width_m: e.target.value === "" ? null : Number(e.target.value) })
                        }
                        className="h-8 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-2 text-[12.5px] focus:border-[var(--accent)] focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-[10.5px] text-[var(--text-muted)]">Largo (m)</label>
                      <input
                        type="number"
                        step="0.01"
                        value={selected.length_m ?? ""}
                        onChange={(e) =>
                          updateSelected({ length_m: e.target.value === "" ? null : Number(e.target.value) })
                        }
                        className="h-8 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-2 text-[12.5px] focus:border-[var(--accent)] focus:outline-none"
                      />
                    </div>
                    <div>
                      <label className="text-[10.5px] text-[var(--text-muted)]">Área (m²)</label>
                      <input
                        type="number"
                        step="0.01"
                        value={selected.area_m2 ?? ""}
                        onChange={(e) =>
                          updateSelected({ area_m2: e.target.value === "" ? null : Number(e.target.value) })
                        }
                        className="h-8 w-full rounded-md border border-[var(--border)] bg-[var(--bg-base)] px-2 text-[12.5px] focus:border-[var(--accent)] focus:outline-none"
                      />
                    </div>
                  </div>
                  {scaleRatio != null && selected.polygon && selected.polygon.length >= 3 && (
                    <p className="text-[11px] text-[var(--text-muted)]">
                      <MapPin className="mr-1 inline h-3 w-3" />
                      Área medida: {fmt(polygonAreaM2(selected.polygon, scaleRatio), 2)} m² (escala activa)
                    </p>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={deleteSelected}
                    className="gap-1.5 text-[var(--danger)]"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Eliminar
                  </Button>
                </div>
              ) : (
                <p className="text-[11.5px] text-[var(--text-muted)]">
                  Selecciona una habitación en la lista o en el plano.
                </p>
              )}
            </section>

            <section className="rounded-md border border-dashed border-[var(--border)] bg-[var(--bg-surface-2)]/40 p-2 text-[11px] text-[var(--text-muted)]">
              <p className="font-semibold uppercase tracking-wide">Atajos</p>
              <ul className="mt-1 space-y-0.5">
                <li>· <kbd className="rounded bg-[var(--bg-base)] px-1 font-mono text-[10px]">Esc</kbd> cancela el dibujo actual</li>
                <li>· Doble-click cierra un polígono</li>
                <li>· <b>Sugerir con IA</b> usa el vision model</li>
              </ul>
            </section>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function ToolButton({
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function polygonAreaM2(points: Point[], scaleMperPx: number): number {
  // Shoelace in normalised coords -> px^2 -> m^2
  let area = 0
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    area += (points[j].x + points[i].x) * (points[j].y - points[i].y)
  }
  return Math.abs(area / 2) * scaleMperPx * scaleMperPx
}

function Breadcrumbs({ items }: { items: { label: string }[] }) {
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
