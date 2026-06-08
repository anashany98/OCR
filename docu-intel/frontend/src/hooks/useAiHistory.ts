import { useQuery } from "@tanstack/react-query"

import { api } from "@/api/client"
import type { AIQuestion } from "@/types/api"

/**
 * F8 - Testable data hook for the ChatPage history sidebar.
 *
 * Before F8, this was a single ``useQuery`` call inlined in
 * ``ChatPage.tsx``. Extracting it lets us:
 *
 *   1. unit-test the polling behaviour without rendering the whole
 *      chat tree (the previous code coupled history with streaming
 *      and follow-up state);
 *   2. share the same query key / cadence with the rest of the app
 *      (a "Clear history" admin tool, for example, can already
 *      invalidate ``["ai-history"]``);
 *   3. keep the ``ChatPage`` body focused on UI concerns.
 *
 * The hook returns the raw TanStack Query result so the caller can
 * decide what to do with loading and error states (the original page
 * renders the sidebar even when the request fails).
 */
export function useAiHistory(refetchIntervalMs = 30_000) {
  return useQuery({
    queryKey: ["ai-history"],
    queryFn: api.aiHistory,
    refetchInterval: refetchIntervalMs,
  })
}

/**
 * Convenience type for callers that want the resolved list of
 * questions, with the same default the rest of the app uses.
 */
export type AiHistory = AIQuestion[]

export function selectAiHistory(data: AIQuestion[] | undefined): AiHistory {
  return data ?? []
}
