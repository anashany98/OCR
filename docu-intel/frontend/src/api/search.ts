import type { SavedSearch, SearchResult } from "@/types/api"
import { request } from "./core"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1"

export const searchApi = {
  exportSearchCSV: (query: string, limit = 100) => {
    window.open(`${API_BASE_URL}` + "/search/export/csv?q=" + encodeURIComponent(query) + "&limit=" + limit, "_blank")
  },
  exportSearchJSON: (query: string, limit = 100) => {
    window.open(`${API_BASE_URL}` + "/search/export/json?q=" + encodeURIComponent(query) + "&limit=" + limit, "_blank")
  },
  textSearch: (query: string) => request<SearchResult[]>(`/search/text?q=` + encodeURIComponent(query)),
  guidedSearch: (query: string, mode: string) =>
    request<SearchResult[]>(`/search/guided?mode=` + encodeURIComponent(mode) + `&q=` + encodeURIComponent(query)),
  semanticSearch: (query: string, filters?: Record<string, unknown>) =>
    request<SearchResult[]>("/search/semantic", {
      method: "POST",
      body: JSON.stringify({ query, filters, limit: 20 }),
    }),
  hybridSearch: (query: string, filters?: Record<string, unknown>) =>
    request<SearchResult[]>("/search/hybrid", {
      method: "POST",
      body: JSON.stringify({ query, filters, limit: 20 }),
    }),
  savedSearches: () => request<SavedSearch[]>("/search/saved"),
  createSavedSearch: (payload: { name: string; query: string; mode?: string; filters_json?: Record<string, unknown> }) =>
    request<SavedSearch>("/search/saved", { method: "POST", body: JSON.stringify(payload) }),
}
