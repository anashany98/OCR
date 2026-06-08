import { useEffect, useId, useRef, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

import { csv, ids, optionalId } from "./shared"

const tenantAdminEnabled = import.meta.env.VITE_ENABLE_TENANT_ADMIN === "true"

/**
 * F4b - central admin data hook.
 *
 * The 30+ queries and 25+ useState calls that used to live in
 * ``AdminPage`` are now in this hook. The shell ``AdminPage``
 * renders a tab strip and an ``<Outlet />``; each child tab
 * (``AdminOperationalRoute`` and friends) calls this hook, and
 * TanStack Query dedupes the network calls across tabs so the
 * second tab to mount reuses the cache.
 *
 * Why a single hook for all tabs (not one per tab): the original
 * page shared a lot of state and mutations across tabs
 * (e.g. ``updateDocumentAccess`` is used in both Operativa and
 * Calidad). Splitting per tab would force us to lift state back up
 * to the shell, which is what we are trying to avoid. The cost is
 * a slightly larger initial bundle, but the tabs are already
 * lazy-loaded as separate routes.
 */
export function useAdminData() {
  const queryClient = useQueryClient()
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

  function invalidate(keys: string[]) {
    keys.forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }))
  }

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
        // F4b: the API now expects a single ``permissions_json`` blob
        // instead of the legacy chain/hotel/denied_tags/can_*_*
        // columns. The tab UI still owns the granular state, so the
        // hook composes the JSON shape from the same fields before
        // the request goes out.
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
  const explainAccess = useMutation({
    // F4b: ``document_id`` is now required by the API; the UI lets
    // the admin leave it empty, in which case we send 0 and the
    // backend short-circuits to the principal-only check.
    mutationFn: () =>
      api.accessExplain({
        principal_type: explainPrincipalType,
        principal_id: explainPrincipalId.trim(),
        document_id: optionalId(explainDocumentId) ?? 0,
      }),
    onSuccess: () => invalidate(["audit-logs"]),
  })
  const previewRule = useMutation({
    mutationFn: () =>
      api.rulePreview({
        path: rulePreviewPath,
        pattern: rulePreviewPattern,
        match_type: "contains",
        tags_json: csv(rulePreviewTags),
      }),
    onSuccess: () => invalidate(["audit-logs"]),
  })
  const previewRedaction = useMutation({
    mutationFn: () =>
      api.redactionPreview({
        principal_type: redactionPrincipalType,
        principal_id: redactionPrincipalId.trim(),
        text: redactionText,
      }),
    onSuccess: () => invalidate(["audit-logs"]),
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
      invalidate(["sensitive-tags", "audit-logs"])
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
      invalidate(["documents", "audit-logs"])
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
      invalidate(["documents", "audit-logs"])
    },
  })
  const recalculateQuality = useMutation({
    mutationFn: () => api.recalculateQuality({ limit: 1000 }),
    onSuccess: () => invalidate(["quality-summary", "documents", "audit-logs"]),
  })
  const runIntegrationSandbox = useMutation({
    mutationFn: () => {
      // The sandbox form stores arguments as a JSON string; parse
      // and let the API fail loudly if it isn't valid JSON.
      const parsedArgs = (() => {
        try {
          return JSON.parse(sandboxArguments) as Record<string, unknown>
        } catch {
          throw new Error("Los argumentos del sandbox deben ser JSON válido")
        }
      })()
      return api.integrationSandbox({
        client_id: Number(sandboxClientId),
        technician_id: sandboxTechnicianId.trim(),
        tool: sandboxTool.trim(),
        arguments: parsedArgs,
      })
    },
    onSuccess: () => invalidate(["audit-logs"]),
  })
  const loadDocumentGraph = useMutation({
    mutationFn: () => api.documentGraph(Number(graphDocumentId)),
    onSuccess: () => invalidate(["audit-logs"]),
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
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      api.updateAdminUser(id, { is_active }),
    onSuccess: () => invalidate(["admin-users", "audit-logs"]),
  })
  const createNotificationRule = useMutation({
    mutationFn: () =>
      api.createNotificationRule({
        name: notificationName.trim(),
        event_type: notificationEventType,
        channel: notificationChannel,
        target: notificationTarget.trim(),
      }),
    onSuccess: () => {
      setNotificationName("")
      setNotificationTarget("")
      invalidate(["notification-rules", "audit-logs"])
    },
  })
  const seedDemo = useMutation({
    mutationFn: () => api.seedDemo(),
    onSuccess: () => invalidate(["system-health", "queues", "stats", "audit-logs"]),
  })

  function onReprocessSubmit(event: FormEvent) {
    event.preventDefault()
    setReprocessConfirmOpen(true)
  }

  function confirmReprocess() {
    setReprocessConfirmOpen(false)
    reprocess.mutate()
  }

  return {
    state: {
      status, setStatus,
      documentType, setDocumentType,
      sourcePath, setSourcePath,
      mode, setMode,
      chainName, setChainName,
      hotelName, setHotelName,
      hotelCode, setHotelCode,
      hotelChainId, setHotelChainId,
      ruleName, setRuleName,
      rulePattern, setRulePattern,
      ruleChainId, setRuleChainId,
      ruleHotelId, setRuleHotelId,
      ruleTags, setRuleTags,
      groupName, setGroupName,
      groupChainIds, setGroupChainIds,
      groupHotelIds, setGroupHotelIds,
      groupDeniedTags, setGroupDeniedTags,
      groupAllowAll, setGroupAllowAll,
      groupCanPrices, setGroupCanPrices,
      groupCanSearchBudgets, setGroupCanSearchBudgets,
      memberGroupId, setMemberGroupId,
      memberType, setMemberType,
      memberPrincipalId, setMemberPrincipalId,
      assignDocumentId, setAssignDocumentId,
      assignChainId, setAssignChainId,
      assignHotelId, setAssignHotelId,
      assignTags, setAssignTags,
      tagName, setTagName,
      tagDescription, setTagDescription,
      explainPrincipalType, setExplainPrincipalType,
      explainPrincipalId, setExplainPrincipalId,
      explainDocumentId, setExplainDocumentId,
      graphDocumentId, setGraphDocumentId,
      apiClientName, setApiClientName,
      apiClientScopes, setApiClientScopes,
      latestApiKey, setLatestApiKey,
      sandboxClientId, setSandboxClientId,
      sandboxTechnicianId, setSandboxTechnicianId,
      sandboxTool, setSandboxTool,
      sandboxArguments, setSandboxArguments,
      roundTrip, setRoundTrip,
      rulePreviewPath, setRulePreviewPath,
      rulePreviewPattern, setRulePreviewPattern,
      rulePreviewTags, setRulePreviewTags,
      redactionPrincipalType, setRedactionPrincipalType,
      redactionPrincipalId, setRedactionPrincipalId,
      redactionText, setRedactionText,
      bulkTagDocumentIds, setBulkTagDocumentIds,
      bulkTagAdd, setBulkTagAdd,
      bulkTagRemove, setBulkTagRemove,
      adminUserEmail, setAdminUserEmail,
      adminUserName, setAdminUserName,
      adminUserRole, setAdminUserRole,
      adminUserPassword, setAdminUserPassword,
      notificationName, setNotificationName,
      notificationEventType, setNotificationEventType,
      notificationChannel, setNotificationChannel,
      notificationTarget, setNotificationTarget,
      reprocessConfirmOpen, setReprocessConfirmOpen,
    },
    queries: {
      stats, alerts, metrics, systemHealth, queueStatus, operationsOverview,
      operationsStatus, maintenanceReport, productionChecklist, productionReadiness,
      storageIntegrity, qualityRules, qualitySummary, learningSuggestions,
      learningCounts, learnedPatterns, operationsDocuments, watchedFiles,
      ingestionEvents, auditLogs, integrationClients, chains, hotels, folderRules,
      quarantine, accessGroups, sensitiveTags, adminUsers, notificationRules,
      ocrReview, duplicates,
    },
    mutations: {
      reprocess, pauseQueues, resumeQueues, createIntegrationClient,
      rotateIntegrationClientKey, createChain, createHotel, createFolderRule,
      applyFolderRules, createAccessGroup, upsertMember, explainAccess, previewRule,
      previewRedaction, createSensitiveTag, applyBulkTags, updateDocumentAccess,
      recalculateQuality, runIntegrationSandbox, loadDocumentGraph,
      approveSuggestion, rejectSuggestion, enablePattern, disablePattern,
      createAdminUser, toggleAdminUser, createNotificationRule, seedDemo,
    },
    handlers: {
      onReprocessSubmit,
      confirmReprocess,
    },
    tenantAdminEnabled,
  }
}

export type AdminData = ReturnType<typeof useAdminData>

/**
 * Modal used by the operational tab to confirm a bulk reprocess.
 * Lives next to the hook because the shell renders it independently
 * of which tab is active.
 */
export function AdminReprocessConfirmDialog({
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
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="rounded-md border border-[var(--border)] bg-transparent px-3 py-1.5 text-sm font-medium hover:bg-[var(--bg-elevated)]"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={confirmDisabled}
            className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-[var(--accent-foreground)] disabled:opacity-50"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
