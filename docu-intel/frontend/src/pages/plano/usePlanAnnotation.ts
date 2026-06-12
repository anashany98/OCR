import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"

import { plansApi, type Plan, type PlanDimension, type PlanRoom } from "@/api/plans"
import { notify } from "@/lib/toast"

import { usePlanSymbols, filterSymbolsByPage } from "./usePlanSymbols"

// ---------------------------------------------------------------------------
// F8b-cont - plan annotation hook
// ---------------------------------------------------------------------------
// Owns every piece of state the plano annotation page needs:
// the plan/rooms/dimensions queries, the local working drafts, the
// tool selection, the canvas interaction handlers, the scale
// computation and the save logic. The page only composes the UI.
// ---------------------------------------------------------------------------

export type Tool = "select" | "room" | "dimension" | "scale"

export type Point = { x: number; y: number }

export const SVG_W = 1200
export const SVG_H = 850

export type DraftRoom = {
  id: number | string
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

export type DraftDimension = {
  id: number | string
  raw_text: string
  value: number | null
  unit: string
  value_m: number | null
  page_number: number | null
  start: Point | null
  end: Point | null
}

/** Pure helper: shoelace area in metres^2 from a polygon + px→m scale. */
export function polygonAreaM2(points: Point[], scaleMperPx: number): number {
  let area = 0
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    area += (points[j].x + points[i].x) * (points[j].y - points[i].y)
  }
  return Math.abs(area / 2) * scaleMperPx * scaleMperPx
}

/** P4 — Helper: nearest point on a line segment to a given point. */
function _nearestPointOnSegment(p: Point, a: Point, b: Point): Point {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) return a
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq))
  return { x: a.x + t * dx, y: a.y + t * dy }
}

export function usePlanAnnotation(documentId: number) {
  const qc = useQueryClient()

  // --- Data fetching --------------------------------------------------------
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

  // --- Local working state -------------------------------------------------
  const [page, setPage] = useState(1)
  const [rooms, setRooms] = useState<DraftRoom[]>([])
  const [dimensions, setDimensions] = useState<DraftDimension[]>([])
  const [tool, setTool] = useState<Tool>("select")
  const [selectedId, setSelectedId] = useState<string | number | null>(null)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [polygonInProgress, setPolygonInProgress] = useState<Point[]>([])
  const [draftDim, setDraftDim] = useState<DraftDimension | null>(null)
  const [scaleLengthM, setScaleLengthM] = useState<string>("")

  // --- Hydration: sync from server -----------------------------------------
  useEffect(() => {
    if (!roomsQuery.data) return
    setRooms(
      roomsQuery.data.map((r: PlanRoom) => ({
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
      dimensionsQuery.data.map((d: PlanDimension) => ({
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

  // --- Vision-assisted suggestions ----------------------------------------
  const [suggesting, setSuggesting] = useState(false)
  const suggest = useCallback(async () => {
    if (!planId) return
    setSuggesting(true)
    try {
      const out = await plansApi.suggestRooms(planId, page)
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

  // --- Canvas interaction --------------------------------------------------
  const svgRef = useRef<SVGSVGElement>(null)
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
          const xi = r.polygon[i].x,
            yi = r.polygon[i].y
          const xj = r.polygon[j].x,
            yj = r.polygon[j].y
          const intersect =
            yi > p.y !== yj > p.y && p.x < ((xj - xi) * (p.y - yi)) / (yj - yi + 1e-9) + xi
          if (intersect) inside = !inside
        }
        if (inside) return r
      }
      return null
    },
    [rooms],
  )

  // P4 — Snap-to-line: find the nearest vertex or edge point from
  // existing rooms and dimensions within a threshold distance.
  const SNAP_THRESHOLD = 8 // SVG units
  const snapPoint = useCallback(
    (p: Point): Point => {
      let best = p
      let bestDist = SNAP_THRESHOLD

      // Check vertices of existing rooms
      for (const r of rooms) {
        if (!r.polygon) continue
        for (const v of r.polygon) {
          const d = Math.sqrt((v.x - p.x) ** 2 + (v.y - p.y) ** 2)
          if (d < bestDist) {
            bestDist = d
            best = v
          }
        }
      }

      // Check dimension endpoints
      for (const d of dimensions) {
        for (const pt of [d.start, d.end]) {
          if (!pt) continue
          const dd = Math.sqrt((pt.x - p.x) ** 2 + (pt.y - p.y) ** 2)
          if (dd < bestDist) {
            bestDist = dd
            best = pt
          }
        }
      }

      // Check edges (nearest point on line segment) of existing rooms
      for (const r of rooms) {
        if (!r.polygon || r.polygon.length < 2) continue
        for (let i = 0; i < r.polygon.length; i++) {
          const a = r.polygon[i]
          const b = r.polygon[(i + 1) % r.polygon.length]
          const nearest = _nearestPointOnSegment(p, a, b)
          const d = Math.sqrt((nearest.x - p.x) ** 2 + (nearest.y - p.y) ** 2)
          if (d < bestDist) {
            bestDist = d
            best = nearest
          }
        }
      }

      return best
    },
    [rooms, dimensions],
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
        setPolygonInProgress((cur) => [...cur, snapPoint(p)])
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
            start: snapPoint(p),
            end: null,
          })
        } else if (draftDim && !draftDim.end) {
          const completed: DraftDimension = { ...draftDim, end: snapPoint(p) }
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
            start: snapPoint(p),
            end: null,
          })
        } else {
          const completed: DraftDimension = { ...draftDim, end: snapPoint(p) }
          setDimensions((cur) => [...cur, completed])
          setDraftDim(null)
          setTool("select")
          setDirty(true)
        }
        return
      }
    },
    [tool, toSvgCoords, hitRoom, snapPoint, draftDim, page],
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

  // --- Selection -----------------------------------------------------------
  const selected = useMemo(() => {
    if (selectedId == null) return null
    return rooms.find((r) => r.id === selectedId) ?? null
  }, [rooms, selectedId])

  const updateSelected = useCallback(
    (patch: Partial<DraftRoom>) => {
      if (selectedId == null) return
      setRooms((cur) => cur.map((r) => (r.id === selectedId ? { ...r, ...patch } : r)))
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

  // --- Project metadata ---------------------------------------------------
  // The project name is persisted via the bulk save; we keep an
  // optimistic in-place mutation on the cached plansList so the
  // header text updates as the user types.
  const setProjectName = useCallback(
    (name: string) => {
      if (plansList.data) {
        const idx = plansList.data.findIndex((p) => p.id === plan?.id)
        if (idx >= 0) plansList.data[idx].project_name = name
      }
      setDirty(true)
    },
    [plansList.data, plan?.id],
  )

  // --- Scale computation --------------------------------------------------
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

  // --- P2 — YOLO plan symbol detection ------------------------------------
  // We attach the symbol hook to the same usePlanAnnotation surface so
  // the page does not need to know about two parallel hooks. The
  // page-filtered overlay is what the canvas actually paints.
  const symbols = usePlanSymbols(planId)
  const visibleSymbolsOnPage = useMemo(
    () => filterSymbolsByPage(symbols.visibleSymbols, page),
    [symbols.visibleSymbols, page],
  )

  // --- Save ----------------------------------------------------------------
  const onSave = useCallback(async () => {
    if (!planId) return
    setSaving(true)
    try {
      const payload: Parameters<typeof plansApi.bulkUpdate>[1] = {
        rooms: rooms.map((r) => ({
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

  return {
    // queries
    plan,
    plansList,
    roomsQuery,
    dimensionsQuery,
    // state
    page,
    setPage,
    rooms,
    setRooms,
    dimensions,
    setDimensions,
    tool,
    setTool,
    selectedId,
    setSelectedId,
    dirty,
    saving,
    polygonInProgress,
    draftDim,
    scaleLengthM,
    setScaleLengthM,
    // computed
    selected,
    scaleDimension,
    scaleRatio,
    // P2 — YOLO plan symbol detection
    symbols,
    visibleSymbolsOnPage,
    // actions
    suggest,
    suggesting,
    onCanvasClick,
    onCanvasDoubleClick,
    onSave,
    updateSelected,
    deleteSelected,
    setProjectName,
    // refs
    svgRef,
  }
}

export type PlanAnnotation = ReturnType<typeof usePlanAnnotation>
