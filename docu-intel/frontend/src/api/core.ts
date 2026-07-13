// Canonical versioned API. Override with VITE_API_BASE_URL at build time.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1"

let onUnauthorized: (() => void) | null = null;

export function setUnauthorizedHandler(cb: () => void): void {
  onUnauthorized = cb;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}` + path, {
    credentials: "include",
    headers:
      options.body instanceof FormData
        ? options.headers
        : { "Content-Type": "application/json", ...options.headers },
    ...options,
  })
  if (response.status === 401) {
    onUnauthorized?.();
  }
  if (!response.ok) {
    let message = response.statusText
    try {
      const payload = await response.json()
      message = payload.detail || message
    } catch {
      // Body was empty or not JSON: fall back to the status
      // text. The empty catch is intentional — we have nothing
      // meaningful to do with the parse error here, and the
      // fallback below (the status text) is already good
      // enough for the user.
    }
    throw new ApiError(message, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export interface BatchUploadResult {
  uploaded: number
  duplicates: number
  failed: number
  documents: {
    document_id: number
    original_filename: string
    status: string
    job_id: number | null
  }[]
}

export function thumbnailUrl(documentId: number) {
  return `${API_BASE_URL}` + "/documents/" + documentId + "/thumbnail"
}

export function documentPreviewUrl(documentId: number) {
  return `${API_BASE_URL}` + "/documents/" + documentId + "/preview"
}

export function pageImageUrl(documentId: number, pageNumber: number) {
  return `${API_BASE_URL}` + "/documents/" + documentId + "/pages/" + pageNumber + "/image"
}

export function downloadUrl(documentId: number) {
  return `${API_BASE_URL}` + "/documents/" + documentId + "/download"
}

export function buildSearchParams(params?: Record<string, unknown>) {
  const search = new URLSearchParams()
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value))
  })
  return search.size ? "?" + search.toString() : ""
}
