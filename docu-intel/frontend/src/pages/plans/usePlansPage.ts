import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

import { parseScaleRatio, numberOrNull } from "./scales"

/**
 * F8 - Plans page data + state hook.
 *
 * The original ``PlansPage`` had 80+ lines of query wiring and
 * three local ``useState`` slots dedicated to the per-plan
 * editor (scale text, measurement label/value/ocr value). This
 * hook owns all of that so the page can focus on layout and the
 * per-section components can stay purely declarative.
 *
 * The hook is the single source of truth for:
 * - ``selectedId`` — the plan currently open in the right column.
 * - ``scaleText`` — the value of the manual scale input; the
 *   ``useEffect`` re-seeds it whenever the user picks a different
 *   plan so they can edit from the current server value.
 * - ``measurementLabel`` / ``measurementValue`` /
 *   ``measurementOcrValue`` — the manual measurement form
 *   (cleared automatically on successful save).
 *
 * The mutation helpers are exposed for the editor so the page
 * shell can keep its render code flat.
 */
export function usePlansPage() {
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
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) =>
      api.updatePlanRoom(id, payload),
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

  // Re-seed the scale input when the user picks a different plan.
  useEffect(() => {
    if (selectedPlan) setScaleText(selectedPlan.scale_text ?? "")
  }, [selectedPlan])

  return {
    state: {
      selectedId,
      setSelectedId,
      scaleText,
      setScaleText,
      measurementLabel,
      setMeasurementLabel,
      measurementValue,
      setMeasurementValue,
      measurementOcrValue,
      setMeasurementOcrValue,
    },
    queries: { plans, rooms, dimensions, measurements },
    data: { selectedPlan },
    mutations: { scale: scaleMutation, room: roomMutation, measurement: measurementMutation },
  }
}

export type PlansData = ReturnType<typeof usePlansPage>
