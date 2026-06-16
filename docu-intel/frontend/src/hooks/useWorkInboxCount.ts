import { useQuery } from "@tanstack/react-query"

import { api } from "@/api/client"

export function useWorkInboxCount() {
  return useQuery({
    queryKey: ["work-inbox-count"],
    queryFn: () => api.workInboxCount(),
    refetchInterval: 30000,
  })
}
