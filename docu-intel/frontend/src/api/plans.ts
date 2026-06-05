import { request } from "./core"

export type PlanRoom = {
  id: number
  plan_id: number
  name: string | null
  area_m2: number | null
  width_m: number | null
  length_m: number | null
  polygon_json: { points: Array<{ x: number; y: number }>; scale_factor?: number } | null
  confidence: number | null
  source: string | null
  needs_review: boolean
}

export type PlanDimension = {
  id: number
  plan_id: number
  raw_text: string | null
  value: number | null
  unit: string | null
  value_m: number | null
  page_number: number | null
  bbox_x1: number | null
  bbox_y1: number | null
  bbox_x2: number | null
  bbox_y2: number | null
  confidence: number | null
}

export type Plan = {
  id: number
  document_id: number
  project_name: string | null
  scale_text: string | null
  scale_ratio: number | null
  unit: string | null
  has_valid_scale: boolean
  scale_confidence: number | null
  created_at: string
}

export type PlanVisionSuggestion = {
  name: string
  bbox: [number, number, number, number]
  confidence: number | null
  rationale: string | null
}

export type PlanVisionSuggestionResponse = {
  project_name: string | null
  scale_text: string | null
  rooms: PlanVisionSuggestion[]
  model: string | null
}

export const plansApi = {
  list: (limit = 50) => request<Plan[]>(`/plans?limit=${limit}`),
  get: (id: number) => request<Plan>(`/plans/${id}`),
  getRooms: (id: number) => request<PlanRoom[]>(`/plans/${id}/rooms`),
  getDimensions: (id: number) => request<PlanDimension[]>(`/plans/${id}/dimensions`),
  bulkUpdate: (
    id: number,
    payload: {
      rooms?: Array<Partial<PlanRoom> & { page_number?: number }>
      dimensions?: Array<Partial<PlanDimension> & { page_number?: number }>
      scale_text?: string | null
      scale_ratio?: number | null
      unit?: string | null
      has_valid_scale?: boolean | null
      project_name?: string | null
    },
  ) =>
    request<Plan>(`/plans/${id}/bulk`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  updateProject: (id: number, project_name: string | null) =>
    request<Plan>(`/plans/${id}/project`, {
      method: "PATCH",
      body: JSON.stringify({ project_name }),
    }),
  updateScale: (
    id: number,
    payload: {
      scale_text?: string | null
      scale_ratio?: number | null
      unit?: string | null
      has_valid_scale?: boolean | null
    },
  ) =>
    request<Plan>(`/plans/${id}/scale`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  suggestRooms: (id: number, page_number = 1) =>
    request<PlanVisionSuggestionResponse>(`/plans/${id}/suggest-rooms`, {
      method: "POST",
      body: JSON.stringify({ page_number }),
    }),
  deleteRoom: (planId: number, roomId: number) =>
    request<void>(`/plans/${planId}/rooms/${roomId}`, { method: "DELETE" }),
  deleteDimension: (planId: number, dimId: number) =>
    request<void>(`/plans/${planId}/dimensions/${dimId}`, { method: "DELETE" }),
}
