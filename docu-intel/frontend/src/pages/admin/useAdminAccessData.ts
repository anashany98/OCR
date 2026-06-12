/**
 * useAdminAccessData - queries and state for the ``/admin/acceso``
 * tab (chains/hotels, folder rules, access groups, members, sensitive
 * tags, redaction explainer, rule preview).
 */
import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

import { csv, ids, optionalId } from "./shared"

const tenantAdminEnabled = import.meta.env.VITE_ENABLE_TENANT_ADMIN === "true"

export function useAdminAccessData() {
  const queryClient = useQueryClient()

  const [chainName, setChainName] = useState("")
  const [hotelName, setHotelName] = useState("")
  const [hotelCode, setHotelCode] = useState("")
  const [hotelChainId, setHotelChainId] = useState("")
  const [ruleName, setRuleName] = useState("")
  const [rulePattern, setRulePattern] = useState("")
  const [ruleChainId, setRuleChainId] = useState("")
  const [ruleHotelId, setRuleHotelId] = useState("")
  const [ruleTags, setRuleTags] = useState("")
  const [groupName, setGroupName] = useState("")
  const [groupChainIds, setGroupChainIds] = useState("")
  const [groupHotelIds, setGroupHotelIds] = useState("")
  const [groupDeniedTags, setGroupDeniedTags] = useState("contabilidad, administracion")
  const [groupAllowAll, setGroupAllowAll] = useState(false)
  const [groupCanPrices, setGroupCanPrices] = useState(false)
  const [groupCanSearchBudgets, setGroupCanSearchBudgets] = useState(false)
  const [memberGroupId, setMemberGroupId] = useState("")
  const [memberType, setMemberType] = useState<"user" | "technician">("technician")
  const [memberPrincipalId, setMemberPrincipalId] = useState("")
  const [tagName, setTagName] = useState("")
  const [tagDescription, setTagDescription] = useState("")
  const [explainPrincipalType, setExplainPrincipalType] = useState<"user" | "technician">(
    "technician",
  )
  const [explainPrincipalId, setExplainPrincipalId] = useState("")
  const [explainDocumentId, setExplainDocumentId] = useState("")
  const [rulePreviewPath, setRulePreviewPath] = useState("")
  const [rulePreviewPattern, setRulePreviewPattern] = useState("/presupuestos/")
  const [rulePreviewTags, setRulePreviewTags] = useState("precios")
  const [redactionPrincipalType, setRedactionPrincipalType] = useState<"user" | "technician">(
    "technician",
  )
  const [redactionPrincipalId, setRedactionPrincipalId] = useState("tecnico-demo")
  const [redactionText, setRedactionText] = useState("Total 1.245,60 € margen 20%")

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
  const folderRules = useQuery({
    queryKey: ["folder-rules"],
    queryFn: api.folderRules,
    enabled: tenantAdminEnabled,
  })
  const accessGroups = useQuery({ queryKey: ["access-groups"], queryFn: api.accessGroups })
  const sensitiveTags = useQuery({ queryKey: ["sensitive-tags"], queryFn: api.sensitiveTags })

  const createChain = useMutation({
    mutationFn: () => api.createHotelChain({ name: chainName.trim() }),
    onSuccess: () => {
      setChainName("")
      void queryClient.invalidateQueries({ queryKey: ["hotel-chains"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const createHotel = useMutation({
    mutationFn: () =>
      api.createHotel({
        chain_id: Number(hotelChainId),
        name: hotelName.trim(),
        code: hotelCode.trim() || null,
      }),
    onSuccess: () => {
      setHotelName("")
      setHotelCode("")
      void queryClient.invalidateQueries({ queryKey: ["hotels"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const createFolderRule = useMutation({
    mutationFn: () =>
      api.createFolderRule({
        name: ruleName.trim() || null,
        pattern: rulePattern.trim(),
        match_type: "contains",
        chain_id: optionalId(ruleChainId),
        hotel_id: optionalId(ruleHotelId),
        tags_json: csv(ruleTags),
      }),
    onSuccess: () => {
      setRuleName("")
      setRulePattern("")
      setRuleTags("")
      void queryClient.invalidateQueries({ queryKey: ["folder-rules"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const applyFolderRules = useMutation({
    mutationFn: () => api.applyFolderRules(false),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["folder-rules"] })
      void queryClient.invalidateQueries({ queryKey: ["quarantine-documents"] })
      void queryClient.invalidateQueries({ queryKey: ["documents"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const createAccessGroup = useMutation({
    mutationFn: () =>
      api.createAccessGroup({
        name: groupName.trim(),
        permissions_json: {
          chain_ids: ids(groupChainIds),
          hotel_ids: ids(groupHotelIds),
          denied_tags: csv(groupDeniedTags),
          allow_all_types: groupAllowAll,
          can_see_prices: groupCanPrices,
          can_search_budgets: groupCanSearchBudgets,
        },
      }),
    onSuccess: () => {
      setGroupName("")
      setGroupChainIds("")
      setGroupHotelIds("")
      void queryClient.invalidateQueries({ queryKey: ["access-groups"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const upsertMember = useMutation({
    mutationFn: () =>
      api.upsertAccessGroupMember(Number(memberGroupId), {
        principal_type: memberType,
        principal_id: memberPrincipalId.trim(),
      }),
    onSuccess: () => {
      setMemberPrincipalId("")
      void queryClient.invalidateQueries({ queryKey: ["access-groups"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const explainAccess = useMutation({
    mutationFn: () =>
      api.accessExplain({
        principal_type: explainPrincipalType,
        principal_id: explainPrincipalId.trim(),
        document_id: optionalId(explainDocumentId) ?? 0,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const previewRule = useMutation({
    mutationFn: () =>
      api.rulePreview({
        path: rulePreviewPath,
        pattern: rulePreviewPattern,
        match_type: "contains",
        tags_json: csv(rulePreviewTags),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const previewRedaction = useMutation({
    mutationFn: () =>
      api.redactionPreview({
        principal_type: redactionPrincipalType,
        principal_id: redactionPrincipalId.trim(),
        text: redactionText,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const createSensitiveTag = useMutation({
    mutationFn: () =>
      api.createSensitiveTag({
        name: tagName.trim(),
        description: tagDescription.trim() || null,
      }),
    onSuccess: () => {
      setTagName("")
      setTagDescription("")
      void queryClient.invalidateQueries({ queryKey: ["sensitive-tags"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })

  return {
    state: {
      chainName,
      setChainName,
      hotelName,
      setHotelName,
      hotelCode,
      setHotelCode,
      hotelChainId,
      setHotelChainId,
      ruleName,
      setRuleName,
      rulePattern,
      setRulePattern,
      ruleChainId,
      setRuleChainId,
      ruleHotelId,
      setRuleHotelId,
      ruleTags,
      setRuleTags,
      groupName,
      setGroupName,
      groupChainIds,
      setGroupChainIds,
      groupHotelIds,
      setGroupHotelIds,
      groupDeniedTags,
      setGroupDeniedTags,
      groupAllowAll,
      setGroupAllowAll,
      groupCanPrices,
      setGroupCanPrices,
      groupCanSearchBudgets,
      setGroupCanSearchBudgets,
      memberGroupId,
      setMemberGroupId,
      memberType,
      setMemberType,
      memberPrincipalId,
      setMemberPrincipalId,
      tagName,
      setTagName,
      tagDescription,
      setTagDescription,
      explainPrincipalType,
      setExplainPrincipalType,
      explainPrincipalId,
      setExplainPrincipalId,
      explainDocumentId,
      setExplainDocumentId,
      rulePreviewPath,
      setRulePreviewPath,
      rulePreviewPattern,
      setRulePreviewPattern,
      rulePreviewTags,
      setRulePreviewTags,
      redactionPrincipalType,
      setRedactionPrincipalType,
      redactionPrincipalId,
      setRedactionPrincipalId,
      redactionText,
      setRedactionText,
    },
    queries: { chains, hotels, folderRules, accessGroups, sensitiveTags },
    mutations: {
      createChain,
      createHotel,
      createFolderRule,
      applyFolderRules,
      createAccessGroup,
      upsertMember,
      explainAccess,
      previewRule,
      previewRedaction,
      createSensitiveTag,
    },
    tenantAdminEnabled,
  }
}

export type AdminAccessData = ReturnType<typeof useAdminAccessData>
