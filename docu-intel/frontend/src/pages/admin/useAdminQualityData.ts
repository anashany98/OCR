/**
 * useAdminQualityData - queries and state for the ``/admin/calidad``
 * tab (quality rules, recalculation, OCR review queue, duplicates,
 * bulk tag application, manual document access assignment).
 */
import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

import { csv, ids, optionalId } from "./shared"

const tenantAdminEnabled = import.meta.env.VITE_ENABLE_TENANT_ADMIN === "true"

export function useAdminQualityData() {
  const queryClient = useQueryClient()

  const [bulkTagDocumentIds, setBulkTagDocumentIds] = useState("")
  const [bulkTagAdd, setBulkTagAdd] = useState("contabilidad")
  const [bulkTagRemove, setBulkTagRemove] = useState("")
  const [assignDocumentId, setAssignDocumentId] = useState("")
  const [assignChainId, setAssignChainId] = useState("")
  const [assignHotelId, setAssignHotelId] = useState("")
  const [assignTags, setAssignTags] = useState("")

  const qualityRules = useQuery({ queryKey: ["quality-rules"], queryFn: api.qualityRules })
  const qualitySummary = useQuery({
    queryKey: ["quality-summary"],
    queryFn: api.qualitySummary,
    refetchInterval: 15000,
  })
  const ocrReview = useQuery({
    queryKey: ["ocr-review"],
    queryFn: () => api.ocrReview({ limit: 50 }),
  })
  const duplicates = useQuery({ queryKey: ["duplicates"], queryFn: api.duplicates })
  const quarantine = useQuery({
    queryKey: ["quarantine-documents"],
    queryFn: api.quarantineDocuments,
    enabled: tenantAdminEnabled,
  })
  // The quality tab also needs chain/hotel lists for the manual
  // access-assignment form. Same ``queryKey`` as the access tab so
  // the second tab to mount reuses the cache.
  const chains = useQuery({
    queryKey: ["hotel-chains"],
    queryFn: api.hotelChains,
    enabled: tenantAdminEnabled,
  })
  const hotels = useQuery({
    queryKey: ["hotels"],
    queryFn: api.hotels,
    enabled: tenantAdminEnabled,
  })

  const recalculateQuality = useMutation({
    mutationFn: () => api.recalculateQuality({ limit: 1000 }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["quality-summary"] })
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const applyBulkTags = useMutation({
    mutationFn: () =>
      api.bulkDocumentTags({
        document_ids: ids(bulkTagDocumentIds),
        add_tags: csv(bulkTagAdd),
        remove_tags: csv(bulkTagRemove),
      }),
    onSuccess: () => {
      setBulkTagDocumentIds("")
      setBulkTagAdd("")
      setBulkTagRemove("")
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const updateDocumentAccess = useMutation({
    mutationFn: () =>
      api.updateDocumentAccess(Number(assignDocumentId), {
        chain_id: optionalId(assignChainId),
        hotel_id: optionalId(assignHotelId),
        tags_json: csv(assignTags),
      }),
    onSuccess: () => {
      setAssignDocumentId("")
      setAssignTags("")
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })

  return {
    state: {
      bulkTagDocumentIds,
      setBulkTagDocumentIds,
      bulkTagAdd,
      setBulkTagAdd,
      bulkTagRemove,
      setBulkTagRemove,
      assignDocumentId,
      setAssignDocumentId,
      assignChainId,
      setAssignChainId,
      assignHotelId,
      setAssignHotelId,
      assignTags,
      setAssignTags,
    },
    queries: { qualityRules, qualitySummary, ocrReview, duplicates, quarantine, chains, hotels },
    mutations: { recalculateQuality, applyBulkTags, updateDocumentAccess },
    tenantAdminEnabled,
  }
}

export type AdminQualityData = ReturnType<typeof useAdminQualityData>
