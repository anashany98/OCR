import { FormEvent, useEffect, useId, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { Button } from "@/components/ui/button"
import { ADMIN_TABS, normalizeAdminTab, type AdminTab } from "@/routes/adminTabs"

import { AdminAccessTab } from "./admin/AdminAccessTab"
import { AdminIntegrationsTab } from "./admin/AdminIntegrationsTab"
import { AdminLearningTab } from "./admin/AdminLearningTab"
import { AdminOperationalTab } from "./admin/AdminOperationalTab"
import { AdminQualityTab } from "./admin/AdminQualityTab"
import { AdminSystemTab } from "./admin/AdminSystemTab"
import { csv, ids, optionalId, parseJsonObject } from "./admin/shared"

const tenantAdminEnabled = import.meta.env.VITE_ENABLE_TENANT_ADMIN === "true"

function tabFromParam(param: string | null): AdminTab {
  return normalizeAdminTab(param)
}

export function AdminPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<AdminTab>(() => tabFromParam(searchParams.get("tab")))
  const [status, setStatus] = useState("failed")
  const [documentType, setDocumentType] = useState("")
  const [sourcePath, setSourcePath] = useState("")
  const [mode, setMode] = useState("full")
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
  const [assignDocumentId, setAssignDocumentId] = useState("")
  const [assignChainId, setAssignChainId] = useState("")
  const [assignHotelId, setAssignHotelId] = useState("")
  const [assignTags, setAssignTags] = useState("")
  const [tagName, setTagName] = useState("")
  const [tagDescription, setTagDescription] = useState("")
  const [explainPrincipalType, setExplainPrincipalType] = useState<"user" | "technician">("technician")
  const [explainPrincipalId, setExplainPrincipalId] = useState("")
  const [explainDocumentId, setExplainDocumentId] = useState("")
  const [graphDocumentId, setGraphDocumentId] = useState("")
  const [apiClientName, setApiClientName] = useState("")
  const [apiClientScopes, setApiClientScopes] = useState("read,upload")
  const [latestApiKey, setLatestApiKey] = useState<string | null>(null)
  const [sandboxClientId, setSandboxClientId] = useState("")
  const [sandboxTechnicianId, setSandboxTechnicianId] = useState("tecnico-demo")
  const [sandboxTool, setSandboxTool] = useState("get_budget_by_number")
  const [sandboxArguments, setSandboxArguments] = useState('{"budget_number":"2026/143"}')
  const [roundTrip, setRoundTrip] = useState(0)
  const [rulePreviewPath, setRulePreviewPath] = useState("")
  const [rulePreviewPattern, setRulePreviewPattern] = useState("/presupuestos/")
  const [rulePreviewTags, setRulePreviewTags] = useState("precios")
  const [redactionPrincipalType, setRedactionPrincipalType] = useState<"user" | "technician">("technician")
  const [redactionPrincipalId, setRedactionPrincipalId] = useState("tecnico-demo")
  const [redactionText, setRedactionText] = useState("Total 1.245,60 € margen 20%")
  const [bulkTagDocumentIds, setBulkTagDocumentIds] = useState("")
  const [bulkTagAdd, setBulkTagAdd] = useState("contabilidad")
  const [bulkTagRemove, setBulkTagRemove] = useState("")
  const [adminUserEmail, setAdminUserEmail] = useState("")
  const [adminUserName, setAdminUserName] = useState("")
  const [adminUserRole, setAdminUserRole] = useState("operario")
  const [adminUserPassword, setAdminUserPassword] = useState("")
  const [notificationName, setNotificationName] = useState("")
  const [notificationEventType, setNotificationEventType] = useState("ocr_failed")
  const [notificationChannel, setNotificationChannel] = useState("webhook")
  const [notificationTarget, setNotificationTarget] = useState("")
  const [reprocessConfirmOpen, setReprocessConfirmOpen] = useState(false)

  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats })
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts })
  const metrics = useQuery({ queryKey: ["processing-metrics"], queryFn: api.processingMetrics })
  const systemHealth = useQuery({ queryKey: ["system-health"], queryFn: api.systemHealth, refetchInterval: 15000 })
  const queueStatus = useQuery({ queryKey: ["queues"], queryFn: api.queues, refetchInterval: 5000 })
  const operationsOverview = useQuery({ queryKey: ["operations-overview"], queryFn: api.operationsOverview, refetchInterval: 5000 })
  const operationsStatus = useQuery({ queryKey: ["operations-status"], queryFn: api.operationsStatus, refetchInterval: 5000 })
  const maintenanceReport = useQuery({ queryKey: ["maintenance-report"], queryFn: api.maintenanceReport, refetchInterval: 15000 })
  const productionChecklist = useQuery({ queryKey: ["production-checklist"], queryFn: api.productionChecklist, refetchInterval: 30000 })
  const productionReadiness = useQuery({ queryKey: ["production-readiness"], queryFn: api.productionReadiness, refetchInterval: 30000 })
  const storageIntegrity = useQuery({ queryKey: ["storage-integrity"], queryFn: () => api.storageIntegrity(1000), refetchInterval: 30000 })
  const qualityRules = useQuery({ queryKey: ["quality-rules"], queryFn: api.qualityRules })
  const qualitySummary = useQuery({ queryKey: ["quality-summary"], queryFn: api.qualitySummary, refetchInterval: 15000 })
  const learningSuggestions = useQuery({ queryKey: ["learning-suggestions"], queryFn: () => api.classificationSuggestions({ limit: 100 }), refetchInterval: 15000 })
  const learningCounts = useQuery({ queryKey: ["learning-counts"], queryFn: api.classificationSuggestionCounts, refetchInterval: 15000 })
  const learnedPatterns = useQuery({ queryKey: ["learned-patterns"], queryFn: () => api.learnedPatterns({ limit: 100 }), refetchInterval: 15000 })
  const operationsDocuments = useQuery({ queryKey: ["operations-documents"], queryFn: () => api.operationsDocuments({ limit: 10 }), refetchInterval: 15000 })
  const watchedFiles = useQuery({ queryKey: ["watched-files"], queryFn: api.watchedFiles, refetchInterval: 5000 })
  const ingestionEvents = useQuery({ queryKey: ["ingestion-events"], queryFn: api.ingestionEvents, refetchInterval: 5000 })
  const auditLogs = useQuery({ queryKey: ["audit-logs"], queryFn: api.auditLogs })
  const integrationClients = useQuery({ queryKey: ["integration-clients"], queryFn: api.integrationClients })
  const chains = useQuery({ queryKey: ["hotel-chains"], queryFn: api.hotelChains, enabled: tenantAdminEnabled })
  const hotels = useQuery({ queryKey: ["hotels"], queryFn: api.hotels, enabled: tenantAdminEnabled })
  const folderRules = useQuery({ queryKey: ["folder-rules"], queryFn: api.folderRules, enabled: tenantAdminEnabled })
  const quarantine = useQuery({ queryKey: ["quarantine-documents"], queryFn: api.quarantineDocuments, enabled: tenantAdminEnabled })
  const accessGroups = useQuery({ queryKey: ["access-groups"], queryFn: api.accessGroups })
  const sensitiveTags = useQuery({ queryKey: ["sensitive-tags"], queryFn: api.sensitiveTags })
  const adminUsers = useQuery({ queryKey: ["admin-users"], queryFn: api.adminUsers })
  const notificationRules = useQuery({ queryKey: ["notification-rules"], queryFn: api.notificationRules })
  const ocrReview = useQuery({ queryKey: ["ocr-review"], queryFn: () => api.ocrReview({ limit: 50 }) })
  const duplicates = useQuery({ queryKey: ["duplicates"], queryFn: api.duplicates })

  const reprocess = useMutation({
    mutationFn: () =>
      api.reprocessBulk({
        status: status || null,
        document_type: documentType || null,
        source_path_contains: sourcePath || null,
        mode,
        limit: 100,
      }),
    onSuccess: () => invalidate(["jobs", "audit-logs", "stats"]),
  })
  const pauseQueues = useMutation({
    mutationFn: api.pauseQueues,
    onSuccess: () => invalidate(["queues", "audit-logs"]),
  })
  const resumeQueues = useMutation({
    mutationFn: api.resumeQueues,
    onSuccess: () => invalidate(["queues", "audit-logs"]),
  })
  const createIntegrationClient = useMutation({
    mutationFn: () =>
      api.createIntegrationClient({
        name: apiClientName.trim(),
        scopes: csv(apiClientScopes),
      }),
    onSuccess: (client) => {
      setApiClientName("")
      setLatestApiKey(client.api_key ?? null)
      invalidate(["integration-clients", "audit-logs"])
    },
  })
  const rotateIntegrationClientKey = useMutation({
    mutationFn: (clientId: number) => api.rotateIntegrationClientKey(clientId),
    onSuccess: (client) => {
      setLatestApiKey(client.api_key ?? null)
      invalidate(["integration-clients", "audit-logs"])
    },
  })
  const createChain = useMutation({
    mutationFn: () => api.createHotelChain({ name: chainName.trim() }),
    onSuccess: () => {
      setChainName("")
      invalidate(["hotel-chains", "audit-logs"])
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
      invalidate(["hotels", "audit-logs"])
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
      invalidate(["folder-rules", "audit-logs"])
    },
  })
  const applyFolderRules = useMutation({
    mutationFn: () => api.applyFolderRules(false),
    onSuccess: () => invalidate(["folder-rules", "quarantine-documents", "documents", "audit-logs"]),
  })
  const createAccessGroup = useMutation({
    mutationFn: () =>
      api.createAccessGroup({
        name: groupName.trim(),
        permissions_json: {
          chain_ids: tenantAdminEnabled ? ids(groupChainIds) : [],
          hotel_ids: tenantAdminEnabled ? ids(groupHotelIds) : [],
          allow_all_hotels: tenantAdminEnabled ? groupAllowAll : true,
          denied_tags: csv(groupDeniedTags),
          can_view_prices: groupCanPrices,
          can_search_budgets: groupCanSearchBudgets,
        },
      }),
    onSuccess: () => {
      setGroupName("")
      invalidate(["access-groups", "audit-logs"])
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
      invalidate(["access-groups", "audit-logs"])
    },
  })
  const updateDocumentAccess = useMutation({
    mutationFn: () =>
      api.updateDocumentAccess(Number(assignDocumentId), {
        chain_id: optionalId(assignChainId),
        hotel_id: optionalId(assignHotelId),
        assignment_status: optionalId(assignChainId) || optionalId(assignHotelId) ? "assigned" : "quarantine",
        tags_json: csv(assignTags),
        locked_manual: true,
      }),
    onSuccess: () => {
      setAssignDocumentId("")
      invalidate(["quarantine-documents", "documents", "audit-logs"])
    },
  })
  const createSensitiveTag = useMutation({
    mutationFn: () => api.createSensitiveTag({ name: tagName.trim(), description: tagDescription.trim() || null }),
    onSuccess: () => {
      setTagName("")
      setTagDescription("")
      invalidate(["sensitive-tags", "audit-logs"])
    },
  })
  const createAdminUser = useMutation({
    mutationFn: () =>
      api.createAdminUser({
        email: adminUserEmail.trim(),
        name: adminUserName.trim(),
        role: adminUserRole,
        password: adminUserPassword,
      }),
    onSuccess: () => {
      setAdminUserEmail("")
      setAdminUserName("")
      setAdminUserPassword("")
      invalidate(["admin-users", "audit-logs"])
    },
  })
  const toggleAdminUser = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => api.updateAdminUser(id, { is_active }),
    onSuccess: () => invalidate(["admin-users", "audit-logs"]),
  })
  const createNotificationRule = useMutation({
    mutationFn: () =>
      api.createNotificationRule({
        name: notificationName.trim(),
        event_type: notificationEventType.trim(),
        channel: notificationChannel,
        target: notificationTarget.trim(),
        is_active: true,
        filters_json: {},
      }),
    onSuccess: () => {
      setNotificationName("")
      setNotificationTarget("")
      invalidate(["notification-rules", "audit-logs"])
    },
  })
  const seedDemo = useMutation({
    mutationFn: api.seedDemo,
    onSuccess: () => invalidate(["documents", "stats", "audit-logs", "admin-users", "notification-rules"]),
  })
  const explainAccess = useMutation({
    mutationFn: () =>
      api.accessExplain({
        principal_type: explainPrincipalType,
        principal_id: explainPrincipalId.trim(),
        document_id: Number(explainDocumentId),
      }),
  })
  const loadDocumentGraph = useMutation({
    mutationFn: () => api.documentGraph(Number(graphDocumentId)),
  })
  const previewRule = useMutation({
    mutationFn: () =>
      api.rulePreview({
        path: rulePreviewPath.trim(),
        pattern: rulePreviewPattern.trim(),
        match_type: "contains",
        tags_json: csv(rulePreviewTags),
      }),
  })
  const runIntegrationSandbox = useMutation({
    mutationFn: () =>
      api.integrationSandbox({
        client_id: Number(sandboxClientId),
        technician_id: sandboxTechnicianId.trim(),
        tool: sandboxTool.trim(),
        arguments: parseJsonObject(sandboxArguments),
      }),
  })
  const previewRedaction = useMutation({
    mutationFn: () =>
      api.redactionPreview({
        principal_type: redactionPrincipalType,
        principal_id: redactionPrincipalId.trim(),
        text: redactionText,
      }),
  })
  const recalculateQuality = useMutation({
    mutationFn: () => api.recalculateQuality({ limit: 1000 }),
    onSuccess: () => invalidate(["quality-summary", "operations-overview", "work-inbox"]),
  })
  const approveSuggestion = useMutation({
    mutationFn: (id: number) => api.approveSuggestion(id),
    onSuccess: () => invalidate(["learning-suggestions", "learning-counts", "audit-logs"]),
  })
  const rejectSuggestion = useMutation({
    mutationFn: (id: number) => api.rejectSuggestion(id),
    onSuccess: () => invalidate(["learning-suggestions", "learning-counts", "audit-logs"]),
  })
  const enablePattern = useMutation({
    mutationFn: (id: number) => api.enablePattern(id),
    onSuccess: () => invalidate(["learned-patterns", "audit-logs"]),
  })
  const disablePattern = useMutation({
    mutationFn: (id: number) => api.disablePattern(id),
    onSuccess: () => invalidate(["learned-patterns", "audit-logs"]),
  })
  const applyBulkTags = useMutation({
    mutationFn: () =>
      api.bulkDocumentTags({
        document_ids: ids(bulkTagDocumentIds),
        add_tags: csv(bulkTagAdd),
        remove_tags: csv(bulkTagRemove),
      }),
    onSuccess: () => invalidate(["documents", "operations-documents", "audit-logs"]),
  })

  function invalidate(keys: string[]) {
    keys.forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }))
  }

  function onReprocessSubmit(event: FormEvent) {
    event.preventDefault()
    setReprocessConfirmOpen(true)
  }

  function confirmReprocess() {
    setReprocessConfirmOpen(false)
    reprocess.mutate()
  }

  function switchTab(tab: AdminTab) {
    setActiveTab(tab)
    setSearchParams({ tab }, { replace: true })
  }

  // Sync tab from URL on back/forward navigation
  useEffect(() => {
    const param = searchParams.get("tab")
    if (param) {
      const mapped = tabFromParam(param)
      if (mapped !== activeTab) setActiveTab(mapped)
    }
  }, [searchParams])

  return (
    <>
      <PageHeader title="Administración" description="Operación documental, integración segura, colas y auditoría." />
      <div className="mb-4 flex flex-wrap gap-2">
        {ADMIN_TABS.map(({ id: tabId, label, icon: Icon }) => {
          return (
            <Button key={tabId} type="button" variant={activeTab === tabId ? "default" : "outline"} size="sm" onClick={() => switchTab(tabId)}>
              <Icon data-icon="inline-start" />
              {label}
            </Button>
          )
        })}
      </div>

      {activeTab === "operativa" ? (
        <AdminOperationalTab
          auditLogs={auditLogs.data ?? []}
          alerts={alerts.data ?? []}
          metrics={metrics.data}
          queueStatus={queueStatus.data}
          operationsOverview={operationsOverview.data}
          operationsStatus={operationsStatus.data}
          maintenanceReport={maintenanceReport.data}
          operationsDocuments={operationsDocuments.data}
          watchedFiles={watchedFiles.data ?? []}
          ingestionEvents={ingestionEvents.data ?? []}
          stats={stats.data}
          status={status}
          setStatus={setStatus}
          documentType={documentType}
          setDocumentType={setDocumentType}
          sourcePath={sourcePath}
          setSourcePath={setSourcePath}
          mode={mode}
          setMode={setMode}
          reprocessPending={reprocess.isPending}
          reprocessResult={reprocess.data}
          reprocessError={reprocess.isError ? reprocess.error.message : null}
          onReprocessSubmit={onReprocessSubmit}
          pauseQueues={{ mutate: () => pauseQueues.mutate(), isPending: pauseQueues.isPending, data: pauseQueues.data, isError: pauseQueues.isError, error: pauseQueues.error }}
          resumeQueues={{ mutate: () => resumeQueues.mutate(), isPending: resumeQueues.isPending, data: resumeQueues.data, isError: resumeQueues.isError, error: resumeQueues.error }}
          graphDocumentId={graphDocumentId}
          setGraphDocumentId={setGraphDocumentId}
          loadDocumentGraph={{ mutate: () => loadDocumentGraph.mutate(), isPending: loadDocumentGraph.isPending, data: loadDocumentGraph.data, isError: loadDocumentGraph.isError, error: loadDocumentGraph.error }}
        />
      ) : null}

      {activeTab === "sistema" ? (
        <AdminSystemTab
          systemHealth={systemHealth.data}
          productionChecklist={productionChecklist.data}
          productionReadiness={productionReadiness.data}
          maintenanceReport={maintenanceReport.data}
          storageIntegrity={storageIntegrity.data}
          adminUsers={adminUsers.data ?? []}
          notificationRules={notificationRules.data ?? []}
          operationsStatus={operationsStatus.data}
          queueStatus={queueStatus.data}
          operationsOverview={operationsOverview.data}
          stats={stats.data}
          adminUserEmail={adminUserEmail}
          setAdminUserEmail={setAdminUserEmail}
          adminUserName={adminUserName}
          setAdminUserName={setAdminUserName}
          adminUserRole={adminUserRole}
          setAdminUserRole={setAdminUserRole}
          adminUserPassword={adminUserPassword}
          setAdminUserPassword={setAdminUserPassword}
          createAdminUser={{ mutate: () => createAdminUser.mutate(), isPending: createAdminUser.isPending, data: createAdminUser.data, isError: createAdminUser.isError, error: createAdminUser.error }}
          toggleAdminUser={{ mutate: toggleAdminUser.mutate, isPending: toggleAdminUser.isPending }}
          notificationName={notificationName}
          setNotificationName={setNotificationName}
          notificationEventType={notificationEventType}
          setNotificationEventType={setNotificationEventType}
          notificationChannel={notificationChannel}
          setNotificationChannel={setNotificationChannel}
          notificationTarget={notificationTarget}
          setNotificationTarget={setNotificationTarget}
          createNotificationRule={{ mutate: () => createNotificationRule.mutate(), isPending: createNotificationRule.isPending, data: createNotificationRule.data, isError: createNotificationRule.isError, error: createNotificationRule.error }}
          seedDemo={{ mutate: () => seedDemo.mutate(), isPending: seedDemo.isPending, data: seedDemo.data, isError: seedDemo.isError, error: seedDemo.error }}
        />
      ) : null}

      {activeTab === "integraciones" ? (
        <AdminIntegrationsTab
          integrationClients={integrationClients.data ?? []}
          apiClientName={apiClientName}
          setApiClientName={setApiClientName}
          apiClientScopes={apiClientScopes}
          setApiClientScopes={setApiClientScopes}
          createIntegrationClient={{ mutate: () => createIntegrationClient.mutate(), isPending: createIntegrationClient.isPending, data: createIntegrationClient.data, isError: createIntegrationClient.isError, error: createIntegrationClient.error }}
          rotateIntegrationClientKey={{ mutate: rotateIntegrationClientKey.mutate, isPending: rotateIntegrationClientKey.isPending }}
          latestApiKey={latestApiKey}
          setLatestApiKey={setLatestApiKey}
          sandboxClientId={sandboxClientId}
          setSandboxClientId={setSandboxClientId}
          sandboxTechnicianId={sandboxTechnicianId}
          setSandboxTechnicianId={setSandboxTechnicianId}
          sandboxTool={sandboxTool}
          setSandboxTool={setSandboxTool}
          sandboxArguments={sandboxArguments}
          setSandboxArguments={setSandboxArguments}
          runIntegrationSandbox={{ mutate: () => runIntegrationSandbox.mutate(), isPending: runIntegrationSandbox.isPending, data: runIntegrationSandbox.data, isError: runIntegrationSandbox.isError, error: runIntegrationSandbox.error }}
          roundTrip={roundTrip}
          setRoundTrip={setRoundTrip}
        />
      ) : null}

      {activeTab === "acceso" ? (
        <AdminAccessTab
          chains={chains.data ?? []}
          hotels={hotels.data ?? []}
          folderRules={folderRules.data ?? []}
          accessGroups={accessGroups.data ?? []}
          sensitiveTags={sensitiveTags.data ?? []}
          tenantAdminEnabled={tenantAdminEnabled}
          chainName={chainName}
          setChainName={setChainName}
          hotelName={hotelName}
          setHotelName={setHotelName}
          hotelCode={hotelCode}
          setHotelCode={setHotelCode}
          hotelChainId={hotelChainId}
          setHotelChainId={setHotelChainId}
          createChain={{ mutate: () => createChain.mutate(), isPending: createChain.isPending, data: createChain.data, isError: createChain.isError, error: createChain.error }}
          createHotel={{ mutate: () => createHotel.mutate(), isPending: createHotel.isPending, data: createHotel.data, isError: createHotel.isError, error: createHotel.error }}
          ruleName={ruleName}
          setRuleName={setRuleName}
          rulePattern={rulePattern}
          setRulePattern={setRulePattern}
          ruleChainId={ruleChainId}
          setRuleChainId={setRuleChainId}
          ruleHotelId={ruleHotelId}
          setRuleHotelId={setRuleHotelId}
          ruleTags={ruleTags}
          setRuleTags={setRuleTags}
          createFolderRule={{ mutate: () => createFolderRule.mutate(), isPending: createFolderRule.isPending, data: createFolderRule.data, isError: createFolderRule.isError, error: createFolderRule.error }}
          applyFolderRules={{ mutate: () => applyFolderRules.mutate(), isPending: applyFolderRules.isPending, data: applyFolderRules.data }}
          groupName={groupName}
          setGroupName={setGroupName}
          groupChainIds={groupChainIds}
          setGroupChainIds={setGroupChainIds}
          groupHotelIds={groupHotelIds}
          setGroupHotelIds={setGroupHotelIds}
          groupDeniedTags={groupDeniedTags}
          setGroupDeniedTags={setGroupDeniedTags}
          groupAllowAll={groupAllowAll}
          setGroupAllowAll={setGroupAllowAll}
          groupCanPrices={groupCanPrices}
          setGroupCanPrices={setGroupCanPrices}
          groupCanSearchBudgets={groupCanSearchBudgets}
          setGroupCanSearchBudgets={setGroupCanSearchBudgets}
          createAccessGroup={{ mutate: () => createAccessGroup.mutate(), isPending: createAccessGroup.isPending, data: createAccessGroup.data, isError: createAccessGroup.isError, error: createAccessGroup.error }}
          memberGroupId={memberGroupId}
          setMemberGroupId={setMemberGroupId}
          memberType={memberType}
          setMemberType={setMemberType}
          memberPrincipalId={memberPrincipalId}
          setMemberPrincipalId={setMemberPrincipalId}
          upsertMember={{ mutate: () => upsertMember.mutate(), isPending: upsertMember.isPending, data: upsertMember.data, isError: upsertMember.isError, error: upsertMember.error }}
          explainPrincipalType={explainPrincipalType}
          setExplainPrincipalType={setExplainPrincipalType}
          explainPrincipalId={explainPrincipalId}
          setExplainPrincipalId={setExplainPrincipalId}
          explainDocumentId={explainDocumentId}
          setExplainDocumentId={setExplainDocumentId}
          explainAccess={{ mutate: () => explainAccess.mutate(), isPending: explainAccess.isPending, data: explainAccess.data, isError: explainAccess.isError, error: explainAccess.error }}
          rulePreviewPath={rulePreviewPath}
          setRulePreviewPath={setRulePreviewPath}
          rulePreviewPattern={rulePreviewPattern}
          setRulePreviewPattern={setRulePreviewPattern}
          rulePreviewTags={rulePreviewTags}
          setRulePreviewTags={setRulePreviewTags}
          previewRule={{ mutate: () => previewRule.mutate(), isPending: previewRule.isPending, data: previewRule.data, isError: previewRule.isError, error: previewRule.error }}
          redactionPrincipalType={redactionPrincipalType}
          setRedactionPrincipalType={setRedactionPrincipalType}
          redactionPrincipalId={redactionPrincipalId}
          setRedactionPrincipalId={setRedactionPrincipalId}
          redactionText={redactionText}
          setRedactionText={setRedactionText}
          previewRedaction={{ mutate: () => previewRedaction.mutate(), isPending: previewRedaction.isPending, data: previewRedaction.data, isError: previewRedaction.isError, error: previewRedaction.error }}
          tagName={tagName}
          setTagName={setTagName}
          tagDescription={tagDescription}
          setTagDescription={setTagDescription}
          createSensitiveTag={{ mutate: () => createSensitiveTag.mutate(), isPending: createSensitiveTag.isPending, data: createSensitiveTag.data, isError: createSensitiveTag.isError, error: createSensitiveTag.error }}
        />
      ) : null}

      {activeTab === "calidad" ? (
        <AdminQualityTab
          qualityRules={qualityRules.data}
          qualitySummary={qualitySummary.data}
          recalculateQuality={{ mutate: () => recalculateQuality.mutate(), isPending: recalculateQuality.isPending, data: recalculateQuality.data, isError: recalculateQuality.isError, error: recalculateQuality.error }}
          ocrReviewPages={ocrReview.data ?? []}
          duplicates={duplicates.data ?? []}
          quarantine={quarantine.data ?? []}
          tenantAdminEnabled={tenantAdminEnabled}
          bulkTagDocumentIds={bulkTagDocumentIds}
          setBulkTagDocumentIds={setBulkTagDocumentIds}
          bulkTagAdd={bulkTagAdd}
          setBulkTagAdd={setBulkTagAdd}
          bulkTagRemove={bulkTagRemove}
          setBulkTagRemove={setBulkTagRemove}
          applyBulkTags={{ mutate: () => applyBulkTags.mutate(), isPending: applyBulkTags.isPending, data: applyBulkTags.data, isError: applyBulkTags.isError, error: applyBulkTags.error }}
          assignDocumentId={assignDocumentId}
          setAssignDocumentId={setAssignDocumentId}
          assignChainId={assignChainId}
          setAssignChainId={setAssignChainId}
          assignHotelId={assignHotelId}
          setAssignHotelId={setAssignHotelId}
          assignTags={assignTags}
          setAssignTags={setAssignTags}
          chains={chains.data ?? []}
          hotels={hotels.data ?? []}
          updateDocumentAccess={{ mutate: () => updateDocumentAccess.mutate(), isPending: updateDocumentAccess.isPending, data: updateDocumentAccess.data, isError: updateDocumentAccess.isError, error: updateDocumentAccess.error }}
        />
      ) : null}

      {activeTab === "aprendizaje" ? (
        <AdminLearningTab
          suggestions={learningSuggestions.data ?? []}
          patterns={learnedPatterns.data ?? []}
          counts={learningCounts.data}
          approveSuggestion={{ mutate: (id: number) => approveSuggestion.mutate(id), isPending: approveSuggestion.isPending, data: approveSuggestion.data, isError: approveSuggestion.isError, error: approveSuggestion.error }}
          rejectSuggestion={{ mutate: (id: number) => rejectSuggestion.mutate(id), isPending: rejectSuggestion.isPending, data: rejectSuggestion.data, isError: rejectSuggestion.isError, error: rejectSuggestion.error }}
          enablePattern={{ mutate: (id: number) => enablePattern.mutate(id), isPending: enablePattern.isPending, data: enablePattern.data, isError: enablePattern.isError, error: enablePattern.error }}
          disablePattern={{ mutate: (id: number) => disablePattern.mutate(id), isPending: disablePattern.isPending, data: disablePattern.data, isError: disablePattern.isError, error: disablePattern.error }}
        />
      ) : null}

      <ConfirmDialog
        open={reprocessConfirmOpen}
        title="Reprocesar documentos"
        description="Esta acción encolará nuevos jobs para los documentos que coincidan con los filtros actuales."
        confirmLabel="Reprocesar"
        confirmDisabled={reprocess.isPending}
        onCancel={() => setReprocessConfirmOpen(false)}
        onConfirm={confirmReprocess}
      />
    </>
  )
}

function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  confirmDisabled = false,
  onCancel,
  onConfirm,
}: {
  open: boolean
  title: string
  description: string
  confirmLabel: string
  confirmDisabled?: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const titleId = useId()
  const descriptionId = useId()
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    cancelRef.current?.focus()

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault()
        onCancel()
      }
    }

    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4">
      <button
        type="button"
        aria-label="Cancelar acción"
        className="absolute inset-0 bg-black/45"
        onClick={onCancel}
        tabIndex={-1}
      />
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        className="relative w-full max-w-md rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-xl"
      >
        <h2 id={titleId} className="text-base font-semibold text-[var(--text-primary)]">
          {title}
        </h2>
        <p id={descriptionId} className="mt-2 text-sm text-[var(--text-secondary)]">
          {description}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button ref={cancelRef} type="button" variant="outline" onClick={onCancel}>
            Cancelar
          </Button>
          <Button type="button" onClick={onConfirm} disabled={confirmDisabled}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
