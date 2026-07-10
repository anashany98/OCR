import {
  AccessGroupsSection,
  AccessSimulatorSection,
  ChainsHotelsSection,
  FolderRulesSection,
  MembersSection,
  RedactionPreviewSection,
  RulePreviewSection,
  SensitiveTagsSection,
} from "./access-sections"
import { useAdminAccessData } from "./useAdminAccessData"

export function AdminAccessPage() {
  const { state, queries, mutations, tenantAdminEnabled } = useAdminAccessData()

  return (
    <div className="space-y-4">
      {tenantAdminEnabled && (
        <ChainsHotelsSection
          chains={queries.chains.data ?? []}
          hotels={queries.hotels.data ?? []}
          chainName={state.chainName}
          setChainName={state.setChainName}
          hotelName={state.hotelName}
          setHotelName={state.setHotelName}
          hotelCode={state.hotelCode}
          setHotelCode={state.setHotelCode}
          hotelChainId={state.hotelChainId}
          setHotelChainId={state.setHotelChainId}
          createChain={{ mutate: () => mutations.createChain.mutate(), isPending: mutations.createChain.isPending, data: mutations.createChain.data, isError: mutations.createChain.isError, error: mutations.createChain.error }}
          createHotel={{ mutate: () => mutations.createHotel.mutate(), isPending: mutations.createHotel.isPending, data: mutations.createHotel.data, isError: mutations.createHotel.isError, error: mutations.createHotel.error }}
        />
      )}

      {tenantAdminEnabled && (
        <FolderRulesSection
          chains={queries.chains.data ?? []}
          hotels={queries.hotels.data ?? []}
          folderRules={queries.folderRules.data ?? []}
          ruleName={state.ruleName}
          setRuleName={state.setRuleName}
          rulePattern={state.rulePattern}
          setRulePattern={state.setRulePattern}
          ruleChainId={state.ruleChainId}
          setRuleChainId={state.setRuleChainId}
          ruleHotelId={state.ruleHotelId}
          setRuleHotelId={state.setRuleHotelId}
          ruleTags={state.ruleTags}
          setRuleTags={state.setRuleTags}
          createFolderRule={{ mutate: () => mutations.createFolderRule.mutate(), isPending: mutations.createFolderRule.isPending, data: mutations.createFolderRule.data, isError: mutations.createFolderRule.isError, error: mutations.createFolderRule.error }}
          applyFolderRules={{ mutate: () => mutations.applyFolderRules.mutate(), isPending: mutations.applyFolderRules.isPending, data: mutations.applyFolderRules.data }}
        />
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <AccessGroupsSection
          accessGroups={queries.accessGroups.data ?? []}
          tenantAdminEnabled={tenantAdminEnabled}
          groupName={state.groupName}
          setGroupName={state.setGroupName}
          groupChainIds={state.groupChainIds}
          setGroupChainIds={state.setGroupChainIds}
          groupHotelIds={state.groupHotelIds}
          setGroupHotelIds={state.setGroupHotelIds}
          groupDeniedTags={state.groupDeniedTags}
          setGroupDeniedTags={state.setGroupDeniedTags}
          groupAllowAll={state.groupAllowAll}
          setGroupAllowAll={state.setGroupAllowAll}
          groupCanPrices={state.groupCanPrices}
          setGroupCanPrices={state.setGroupCanPrices}
          groupCanSearchBudgets={state.groupCanSearchBudgets}
          setGroupCanSearchBudgets={state.setGroupCanSearchBudgets}
          createAccessGroup={{ mutate: () => mutations.createAccessGroup.mutate(), isPending: mutations.createAccessGroup.isPending, data: mutations.createAccessGroup.data, isError: mutations.createAccessGroup.isError, error: mutations.createAccessGroup.error }}
        />
        <MembersSection
          accessGroups={queries.accessGroups.data ?? []}
          memberGroupId={state.memberGroupId}
          setMemberGroupId={state.setMemberGroupId}
          memberType={state.memberType}
          setMemberType={state.setMemberType}
          memberPrincipalId={state.memberPrincipalId}
          setMemberPrincipalId={state.setMemberPrincipalId}
          upsertMember={{ mutate: () => mutations.upsertMember.mutate(), isPending: mutations.upsertMember.isPending, data: mutations.upsertMember.data, isError: mutations.upsertMember.isError, error: mutations.upsertMember.error }}
        />
      </div>

      <SensitiveTagsSection
        sensitiveTags={queries.sensitiveTags.data ?? []}
        tagName={state.tagName}
        setTagName={state.setTagName}
        tagDescription={state.tagDescription}
        setTagDescription={state.setTagDescription}
        createSensitiveTag={{ mutate: () => mutations.createSensitiveTag.mutate(), isPending: mutations.createSensitiveTag.isPending, data: mutations.createSensitiveTag.data, isError: mutations.createSensitiveTag.isError, error: mutations.createSensitiveTag.error }}
      />

      <div className="grid gap-4 xl:grid-cols-3">
        <AccessSimulatorSection
          explainPrincipalType={state.explainPrincipalType}
          setExplainPrincipalType={state.setExplainPrincipalType}
          explainPrincipalId={state.explainPrincipalId}
          setExplainPrincipalId={state.setExplainPrincipalId}
          explainDocumentId={state.explainDocumentId}
          setExplainDocumentId={state.setExplainDocumentId}
          explainAccess={{ mutate: () => mutations.explainAccess.mutate(), isPending: mutations.explainAccess.isPending, data: mutations.explainAccess.data, isError: mutations.explainAccess.isError, error: mutations.explainAccess.error }}
        />
        <RulePreviewSection
          rulePreviewPath={state.rulePreviewPath}
          setRulePreviewPath={state.setRulePreviewPath}
          rulePreviewPattern={state.rulePreviewPattern}
          setRulePreviewPattern={state.setRulePreviewPattern}
          rulePreviewTags={state.rulePreviewTags}
          setRulePreviewTags={state.setRulePreviewTags}
          previewRule={{ mutate: () => mutations.previewRule.mutate(), isPending: mutations.previewRule.isPending, data: mutations.previewRule.data, isError: mutations.previewRule.isError, error: mutations.previewRule.error }}
        />
        <RedactionPreviewSection
          redactionPrincipalType={state.redactionPrincipalType}
          setRedactionPrincipalType={state.setRedactionPrincipalType}
          redactionPrincipalId={state.redactionPrincipalId}
          setRedactionPrincipalId={state.setRedactionPrincipalId}
          redactionText={state.redactionText}
          setRedactionText={state.setRedactionText}
          previewRedaction={{ mutate: () => mutations.previewRedaction.mutate(), isPending: mutations.previewRedaction.isPending, data: mutations.previewRedaction.data, isError: mutations.previewRedaction.isError, error: mutations.previewRedaction.error }}
        />
      </div>
    </div>
  )
}
