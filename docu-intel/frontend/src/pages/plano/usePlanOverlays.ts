/**
 * PM7 — Overlay and confirmation hooks for the plan viewer.
 *
 * Fetches overlay data (cajetín regions, chat facts, revision changes)
 * and provides confirmation/correction actions with audit trail.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useCallback, useState } from "react"

import { request } from "@/api/core"
import { queryKeys } from "@/lib/queryKeys"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type OverlayRegion = {
  region_type: string
  bbox: [number, number, number, number]
  label: string
  confidence: number
  page_number: number
}

export type ChatFactOverlay = {
  fact_type: string
  subject: string
  value: string
  bbox: [number, number, number, number] | null
  page_number: number
  source_document: string
  confidence: number
}

export type RevisionChange = {
  change_type: string
  entity_type: string
  description: string
  bbox_old: [number, number, number, number] | null
  bbox_new: [number, number, number, number] | null
  page_number: number
}

export type OverlayVisibility = {
  cajetin: boolean
  legend: boolean
  chatFacts: boolean
  revisions: boolean
  dimensions: boolean
  rooms: boolean
  symbols: boolean
}

// ---------------------------------------------------------------------------
// Hook: usePlanOverlays
// ---------------------------------------------------------------------------

export function usePlanOverlays(planId: number | null, documentId: number | null) {
  const qc = useQueryClient()
  const [visibility, setVisibility] = useState<OverlayVisibility>({
    cajetin: true,
    legend: true,
    chatFacts: false,
    revisions: false,
    dimensions: true,
    rooms: true,
    symbols: true,
  })

  // Fetch overlay regions
  const overlays = useQuery({
    queryKey: queryKeys.plans.overlays(planId ?? 0),
    queryFn: () => request<OverlayRegion[]>(`/plans/${planId}/overlays`),
    enabled: !!planId,
  })

  // Fetch chat facts
  const chatFacts = useQuery({
    queryKey: queryKeys.plans.chatFacts(planId ?? 0),
    queryFn: () => request<ChatFactOverlay[]>(`/plans/${planId}/chat-facts`),
    enabled: !!planId && visibility.chatFacts,
  })

  // Fetch revision changes
  const revisions = useQuery({
    queryKey: queryKeys.plans.revisions(planId ?? 0),
    queryFn: () => request<RevisionChange[]>(`/plans/${planId}/revisions`),
    enabled: !!planId && visibility.revisions,
  })

  // Confirm room
  const confirmRoom = useMutation({
    mutationFn: async ({ roomId, action, notes }: { roomId: number; action: "confirm" | "reject"; notes?: string }) => {
      return request(`/plans/${planId}/rooms/${roomId}/confirm`, {
        method: "POST",
        body: JSON.stringify({ action, notes }),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.plans.rooms(String(planId ?? 0)) })
    },
  })

  // Correct room
  const correctRoom = useMutation({
    mutationFn: async ({ roomId, name, polygon, notes }: {
      roomId: number
      name?: string
      polygon?: Array<{ x: number; y: number }>
      notes?: string
    }) => {
      return request(`/plans/${planId}/rooms/${roomId}`, {
        method: "PATCH",
        body: JSON.stringify({ name, polygon, notes }),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.plans.rooms(String(planId ?? 0)) })
    },
  })

  // Confirm dimension
  const confirmDimension = useMutation({
    mutationFn: async ({ dimId, action }: { dimId: number; action: "confirm" | "reject" }) => {
      return request(`/plans/${planId}/dimensions/${dimId}/confirm`, {
        method: "POST",
        body: JSON.stringify({ action }),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.plans.dimensions(String(planId ?? 0)) })
    },
  })

  // Calibrate scale
  const calibrateScale = useMutation({
    mutationFn: async ({ point1, point2, realDistanceM }: {
      point1: { x: number; y: number }
      point2: { x: number; y: number }
      realDistanceM: number
    }) => {
      return request(`/plans/${planId}/confirm-scale`, {
        method: "POST",
        body: JSON.stringify({
          point1, point2, real_distance_m: realDistanceM,
        }),
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.plans.detail(String(planId ?? 0)) })
    },
  })

  // Toggle overlay visibility
  const toggleOverlay = useCallback((key: keyof OverlayVisibility) => {
    setVisibility((v) => ({ ...v, [key]: !v[key] }))
  }, [])

  return {
    visibility,
    toggleOverlay,
    overlays: overlays.data ?? [],
    chatFacts: chatFacts.data ?? [],
    revisions: revisions.data ?? [],
    confirmRoom,
    correctRoom,
    confirmDimension,
    calibrateScale,
  }
}
