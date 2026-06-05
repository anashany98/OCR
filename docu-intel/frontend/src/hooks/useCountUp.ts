import { useEffect, useRef, useState } from "react"

/**
 * Smoothly count up to a numeric value. Used for hero numbers (metrics, KPIs).
 * `duration` controls how long the animation runs in ms.
 */
export function useCountUp(target: number, duration = 700, decimals = 0): number {
  const [value, setValue] = useState(target)
  const previousTarget = useRef(target)
  const animationRef = useRef<number | null>(null)

  useEffect(() => {
    if (target === previousTarget.current) return
    const from = previousTarget.current
    const to = target
    const start = performance.now()

    function step(now: number) {
      const t = Math.min(1, (now - start) / duration)
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3)
      const current = from + (to - from) * eased
      setValue(Number(current.toFixed(decimals)))
      if (t < 1) {
        animationRef.current = requestAnimationFrame(step)
      } else {
        previousTarget.current = to
      }
    }

    animationRef.current = requestAnimationFrame(step)
    return () => {
      if (animationRef.current != null) cancelAnimationFrame(animationRef.current)
    }
  }, [target, duration, decimals])

  return value
}
