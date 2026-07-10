import type {
  AccessExplain,
  AccessGroup,
  FolderRule,
  Hotel,
  HotelChain,
  RedactionPreview,
  RulePreview,
  SensitiveTag,
} from "@/types/api"

export interface MutationLike<TData = unknown> {
  mutate: () => void
  isPending: boolean
  data?: TData
  isError: boolean
  error: Error | null
}

export interface ApplyFolderRulesMutation {
  mutate: () => void
  isPending: boolean
  data?: { matched: number; assigned: number; quarantined: number; skipped: number }
}

// --- Focused prop bags per section ---

export interface ChainsSectionProps {
  chains: HotelChain[]
  chainName: string
  setChainName: (v: string) => void
  createChain: MutationLike
}

export interface HotelsSectionProps {
  chains: HotelChain[]
  hotels: Hotel[]
  hotelName: string
  setHotelName: (v: string) => void
  hotelCode: string
  setHotelCode: (v: string) => void
  hotelChainId: string
  setHotelChainId: (v: string) => void
  createHotel: MutationLike
}

export interface FolderRulesSectionProps {
  chains: HotelChain[]
  hotels: Hotel[]
  folderRules: FolderRule[]
  ruleName: string
  setRuleName: (v: string) => void
  rulePattern: string
  setRulePattern: (v: string) => void
  ruleChainId: string
  setRuleChainId: (v: string) => void
  ruleHotelId: string
  setRuleHotelId: (v: string) => void
  ruleTags: string
  setRuleTags: (v: string) => void
  createFolderRule: MutationLike
  applyFolderRules: ApplyFolderRulesMutation
}

export interface AccessGroupsSectionProps {
  accessGroups: AccessGroup[]
  tenantAdminEnabled: boolean
  groupName: string
  setGroupName: (v: string) => void
  groupChainIds: string
  setGroupChainIds: (v: string) => void
  groupHotelIds: string
  setGroupHotelIds: (v: string) => void
  groupDeniedTags: string
  setGroupDeniedTags: (v: string) => void
  groupAllowAll: boolean
  setGroupAllowAll: (v: boolean) => void
  groupCanPrices: boolean
  setGroupCanPrices: (v: boolean) => void
  groupCanSearchBudgets: boolean
  setGroupCanSearchBudgets: (v: boolean) => void
  createAccessGroup: MutationLike
}

export interface MembersSectionProps {
  accessGroups: AccessGroup[]
  memberGroupId: string
  setMemberGroupId: (v: string) => void
  memberType: "user" | "technician"
  setMemberType: (v: "user" | "technician") => void
  memberPrincipalId: string
  setMemberPrincipalId: (v: string) => void
  upsertMember: MutationLike
}

export interface SensitiveTagsSectionProps {
  sensitiveTags: SensitiveTag[]
  tagName: string
  setTagName: (v: string) => void
  tagDescription: string
  setTagDescription: (v: string) => void
  createSensitiveTag: MutationLike
}

export interface AccessSimulatorSectionProps {
  explainPrincipalType: "user" | "technician"
  setExplainPrincipalType: (v: "user" | "technician") => void
  explainPrincipalId: string
  setExplainPrincipalId: (v: string) => void
  explainDocumentId: string
  setExplainDocumentId: (v: string) => void
  explainAccess: MutationLike<AccessExplain>
}

export interface RulePreviewSectionProps {
  rulePreviewPath: string
  setRulePreviewPath: (v: string) => void
  rulePreviewPattern: string
  setRulePreviewPattern: (v: string) => void
  rulePreviewTags: string
  setRulePreviewTags: (v: string) => void
  previewRule: MutationLike<RulePreview>
}

export interface RedactionPreviewSectionProps {
  redactionPrincipalType: "user" | "technician"
  setRedactionPrincipalType: (v: "user" | "technician") => void
  redactionPrincipalId: string
  setRedactionPrincipalId: (v: string) => void
  redactionText: string
  setRedactionText: (v: string) => void
  previewRedaction: MutationLike<RedactionPreview>
}
