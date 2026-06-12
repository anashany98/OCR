import { useCallback, useEffect, useRef, useState } from "react"

/**
 * P1 — Zoom & pan hook for the plan annotation SVG canvas.
 *
 * Manages zoom level (scale factor) and pan offset (x, y) for
 * the SVG viewBox. Supports:
 * - Mouse wheel zoom (ctrl/meta + wheel)
 * - Mouse drag pan (in select mode)
 * - Touch pinch-to-zoom
 * - Double-click to zoom in 2x
 * - Keyboard shortcuts (+, -, 0)
 */
export function useZoomPan({
  minZoom = 0.1,
  maxZoom = 10,
  zoomStep = 1.2,
}: {
  minZoom?: number
  maxZoom?: number
  zoomStep?: number
} = {}) {
  const [zoom, setZoom] = useState(1)
  const [panX, setPanX] = useState(0)
  const [panY, setPanY] = useState(0)
  const isPanning = useRef(false)
  const lastMouse = useRef({ x: 0, y: 0 })
  const lastTouchDist = useRef(0)

  const clampZoom = useCallback(
    (z: number) => Math.min(maxZoom, Math.max(minZoom, z)),
    [minZoom, maxZoom],
  )

  const zoomIn = useCallback(() => setZoom((z) => clampZoom(z * zoomStep)), [clampZoom, zoomStep])
  const zoomOut = useCallback(() => setZoom((z) => clampZoom(z / zoomStep)), [clampZoom, zoomStep])
  const resetZoom = useCallback(() => {
    setZoom(1)
    setPanX(0)
    setPanY(0)
  }, [])

  // Mouse wheel: ctrl/meta + wheel = zoom, wheel = pan
  const handleWheel = useCallback(
    (e: WheelEvent) => {
      e.preventDefault()
      if (e.ctrlKey || e.metaKey) {
        const delta = e.deltaY > 0 ? 1 / zoomStep : zoomStep
        setZoom((z) => clampZoom(z * delta))
      } else if (e.shiftKey) {
        setPanX((p) => p - e.deltaY)
      } else {
        setPanY((p) => p - e.deltaY)
        setPanX((p) => p - e.deltaX)
      }
    },
    [clampZoom, zoomStep],
  )

  // Mouse drag pan
  const handleMouseDown = useCallback((e: React.MouseEvent, tool: string) => {
    if (tool === "select") {
      isPanning.current = true
      lastMouse.current = { x: e.clientX, y: e.clientY }
    }
  }, [])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isPanning.current) return
    const dx = e.clientX - lastMouse.current.x
    const dy = e.clientY - lastMouse.current.y
    lastMouse.current = { x: e.clientX, y: e.clientY }
    setPanX((p) => p + dx)
    setPanY((p) => p + dy)
  }, [])

  const handleMouseUp = useCallback(() => {
    isPanning.current = false
  }, [])

  // Double-click to zoom in 2x
  const handleDoubleClick = useCallback(
    (e: React.MouseEvent, tool: string) => {
      if (tool === "select") {
        e.stopPropagation()
        setZoom((z) => clampZoom(z * 2))
      }
    },
    [clampZoom],
  )

  // Touch pinch-to-zoom
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2) {
      const dx = e.touches[0].clientX - e.touches[1].clientX
      const dy = e.touches[0].clientY - e.touches[1].clientY
      lastTouchDist.current = Math.sqrt(dx * dx + dy * dy)
    }
  }, [])

  const handleTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (e.touches.length === 2) {
        e.preventDefault()
        const dx = e.touches[0].clientX - e.touches[1].clientX
        const dy = e.touches[0].clientY - e.touches[1].clientY
        const dist = Math.sqrt(dx * dx + dy * dy)
        if (lastTouchDist.current > 0) {
          const scale = dist / lastTouchDist.current
          setZoom((z) => clampZoom(z * scale))
        }
        lastTouchDist.current = dist
      }
    },
    [clampZoom],
  )

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === "+" || e.key === "=") zoomIn()
      if (e.key === "-") zoomOut()
      if (e.key === "0") resetZoom()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [zoomIn, zoomOut, resetZoom])

  return {
    zoom,
    panX,
    panY,
    zoomIn,
    zoomOut,
    resetZoom,
    handleWheel,
    handleMouseDown,
    handleMouseMove,
    handleMouseUp,
    handleDoubleClick,
    handleTouchStart,
    handleTouchMove,
    zoomPercent: Math.round(zoom * 100),
  }
}
