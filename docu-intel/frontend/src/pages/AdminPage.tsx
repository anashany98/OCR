import { FormEvent, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Activity, BellRing, Building2, DatabaseZap, FolderCog, HardDrive, KeyRound, Network, Pause, Play, RefreshCw, ShieldCheck, Tags, UserPlus, Users } from "lucide-react"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { Badge, type BadgeProps } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const inputFolders = [
  "/data/input/presupuestos",
  "/data/input/pedidos",
  "/data/input/facturas",
  "/data/input/planos",
  "/data/input/imagenes",
  "/data/input/otros",
]

type AdminTab = "operativa" | "sistema" | "integraciones" | "hoteles" | "reglas" | "grupos" | "cuarentena" | "tags"
const tenantAdminEnabled = import.meta.env.VITE_ENABLE_TENANT_ADMIN === "true"

export function AdminPage() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<AdminTab>("operativa")
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
    reprocess.mutate()
  }

  return (
    <>
      <PageHeader title="Administración" description="Operación documental, integración segura, colas y auditoría." />
      <div className="mb-4 flex flex-wrap gap-2">
        {[
          ["operativa", "Operativa", ShieldCheck],
          ["sistema", "Sistema", DatabaseZap],
          ["integraciones", "Integraciones", KeyRound],
          ...(tenantAdminEnabled
            ? [
                ["hoteles", "Cadenas/Hoteles", Building2],
                ["reglas", "Reglas de carpetas", FolderCog],
                ["cuarentena", "Cuarentena", ShieldCheck],
              ]
            : []),
          ["grupos", "Perfiles/Grupos", Users],
          ["tags", "Tags sensibles", Tags],
        ].map(([id, label, Icon]) => (
          <Button key={String(id)} type="button" variant={activeTab === id ? "default" : "outline"} size="sm" onClick={() => setActiveTab(id as AdminTab)}>
            <Icon data-icon="inline-start" />
            {String(label)}
          </Button>
        ))}
      </div>

      {activeTab === "operativa" ? (
        <OperationalTab
          auditLogs={auditLogs.data ?? []}
          alerts={alerts.data ?? []}
          metrics={metrics.data}
          systemHealth={systemHealth.data}
          queueStatus={queueStatus.data}
          operationsOverview={operationsOverview.data}
          operationsStatus={operationsStatus.data}
          maintenanceReport={maintenanceReport.data}
          productionChecklist={productionChecklist.data}
          productionReadiness={productionReadiness.data}
          storageIntegrity={storageIntegrity.data}
          qualityRules={qualityRules.data}
          qualitySummary={qualitySummary.data}
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
          onSubmit={onReprocessSubmit}
          pauseQueues={pauseQueues}
          resumeQueues={resumeQueues}
          explainPrincipalType={explainPrincipalType}
          setExplainPrincipalType={setExplainPrincipalType}
          explainPrincipalId={explainPrincipalId}
          setExplainPrincipalId={setExplainPrincipalId}
          explainDocumentId={explainDocumentId}
          setExplainDocumentId={setExplainDocumentId}
          explainAccess={explainAccess}
          graphDocumentId={graphDocumentId}
          setGraphDocumentId={setGraphDocumentId}
          loadDocumentGraph={loadDocumentGraph}
          rulePreviewPath={rulePreviewPath}
          setRulePreviewPath={setRulePreviewPath}
          rulePreviewPattern={rulePreviewPattern}
          setRulePreviewPattern={setRulePreviewPattern}
          rulePreviewTags={rulePreviewTags}
          setRulePreviewTags={setRulePreviewTags}
          previewRule={previewRule}
          redactionPrincipalType={redactionPrincipalType}
          setRedactionPrincipalType={setRedactionPrincipalType}
          redactionPrincipalId={redactionPrincipalId}
          setRedactionPrincipalId={setRedactionPrincipalId}
          redactionText={redactionText}
          setRedactionText={setRedactionText}
          previewRedaction={previewRedaction}
          recalculateQuality={recalculateQuality}
          bulkTagDocumentIds={bulkTagDocumentIds}
          setBulkTagDocumentIds={setBulkTagDocumentIds}
          bulkTagAdd={bulkTagAdd}
          setBulkTagAdd={setBulkTagAdd}
          bulkTagRemove={bulkTagRemove}
          setBulkTagRemove={setBulkTagRemove}
          applyBulkTags={applyBulkTags}
        />
      ) : null}

      {activeTab === "sistema" ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <UserPlus className="h-4 w-4" />
                Usuarios y permisos
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <form
                className="grid gap-2 md:grid-cols-[1fr_1fr_150px_180px_auto]"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (adminUserEmail.trim() && adminUserName.trim() && adminUserPassword.length >= 12) createAdminUser.mutate()
                }}
              >
                <Input value={adminUserEmail} onChange={(event) => setAdminUserEmail(event.target.value)} placeholder="email@empresa.com" />
                <Input value={adminUserName} onChange={(event) => setAdminUserName(event.target.value)} placeholder="Nombre" />
                <select className="h-9 rounded-md border bg-background px-3 text-sm" value={adminUserRole} onChange={(event) => setAdminUserRole(event.target.value)}>
                  <option value="operario">Operario</option>
                  <option value="gestor">Gestor</option>
                  <option value="auditor">Auditor</option>
                  <option value="admin">Admin</option>
                </select>
                <Input type="password" value={adminUserPassword} onChange={(event) => setAdminUserPassword(event.target.value)} placeholder="Contraseña temporal" />
                <Button disabled={createAdminUser.isPending || adminUserPassword.length < 12}>Crear</Button>
              </form>
              <div className="max-h-[360px] overflow-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Usuario</TableHead>
                      <TableHead>Rol</TableHead>
                      <TableHead>Estado</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(adminUsers.data ?? []).map((user) => (
                      <TableRow key={user.id}>
                        <TableCell>
                          <p className="font-medium">{user.name}</p>
                          <p className="text-xs text-muted-foreground">{user.email}</p>
                        </TableCell>
                        <TableCell>{user.role}</TableCell>
                        <TableCell>
                          <Badge variant={user.is_active ? "success" : "neutral"}>{user.is_active ? "activo" : "inactivo"}</Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button type="button" variant="outline" size="sm" onClick={() => toggleAdminUser.mutate({ id: user.id, is_active: !user.is_active })}>
                            {user.is_active ? "Desactivar" : "Activar"}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              {createAdminUser.isError ? <p className="text-sm text-destructive">{createAdminUser.error.message}</p> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BellRing className="h-4 w-4" />
                Notificaciones
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <form
                className="grid gap-2 md:grid-cols-[1fr_150px_150px_1fr_auto]"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (notificationName.trim() && notificationEventType.trim() && notificationTarget.trim()) createNotificationRule.mutate()
                }}
              >
                <Input value={notificationName} onChange={(event) => setNotificationName(event.target.value)} placeholder="Nombre regla" />
                <Input value={notificationEventType} onChange={(event) => setNotificationEventType(event.target.value)} placeholder="ocr_failed" />
                <select className="h-9 rounded-md border bg-background px-3 text-sm" value={notificationChannel} onChange={(event) => setNotificationChannel(event.target.value)}>
                  <option value="webhook">Webhook</option>
                  <option value="email">Email</option>
                  <option value="teams">Teams</option>
                </select>
                <Input value={notificationTarget} onChange={(event) => setNotificationTarget(event.target.value)} placeholder="URL o destinatario" />
                <Button disabled={createNotificationRule.isPending}>Crear</Button>
              </form>
              <div className="space-y-2">
                {(notificationRules.data ?? []).map((rule) => (
                  <div key={rule.id} className="rounded-md border p-3 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-medium">{rule.name}</p>
                      <Badge variant={rule.is_active ? "success" : "neutral"}>{rule.channel}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {rule.event_type} → {rule.target}
                    </p>
                  </div>
                ))}
                {!notificationRules.data?.length ? <p className="text-sm text-muted-foreground">Sin reglas de notificación.</p> : null}
              </div>
              {createNotificationRule.isError ? <p className="text-sm text-destructive">{createNotificationRule.error.message}</p> : null}
            </CardContent>
          </Card>

          <Card className="xl:col-span-2">
            <CardHeader>
              <CardTitle>Configuración guiada y demo</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-4">
              <ConfigStatus label="Readiness" value={productionReadiness.data?.status ?? "-"} tone={productionReadiness.data?.status === "ready" ? "success" : "warning"} />
              <ConfigStatus label="OCR" value="paddleocr" tone="neutral" />
              <ConfigStatus label="Embeddings" value="backend" tone="neutral" />
              <ConfigStatus label="Backups" value={maintenanceReport.data ? "auditable" : "sin datos"} tone={maintenanceReport.data ? "success" : "warning"} />
              <div className="md:col-span-4 flex flex-wrap items-center gap-3 rounded-md border bg-slate-50 p-3">
                <Button type="button" onClick={() => seedDemo.mutate()} disabled={seedDemo.isPending}>
                  <DatabaseZap data-icon="inline-start" />
                  Activar datos demo
                </Button>
                <span className="text-sm text-muted-foreground">
                  Crea datos de ejemplo y deja registro de auditoría para presentaciones sin documentos reales.
                </span>
                {seedDemo.data ? <Badge variant="success">Demo preparado</Badge> : null}
                {seedDemo.isError ? <span className="text-sm text-destructive">{seedDemo.error.message}</span> : null}
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {activeTab === "integraciones" ? (
        <Card>
          <CardHeader>
            <CardTitle>Clientes API para IA externa</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <form
              className="grid gap-2 md:grid-cols-[1fr_220px_auto]"
              onSubmit={(event) => {
                event.preventDefault()
                if (apiClientName.trim()) createIntegrationClient.mutate()
              }}
            >
              <Input value={apiClientName} onChange={(event) => setApiClientName(event.target.value)} placeholder="Nombre del cliente" />
              <Input value={apiClientScopes} onChange={(event) => setApiClientScopes(event.target.value)} placeholder="read,upload,admin" />
              <Button disabled={createIntegrationClient.isPending}>
                <KeyRound data-icon="inline-start" />
                Crear
              </Button>
            </form>
            {latestApiKey ? (
              <div className="rounded-md border border-warning/50 bg-warning/10 p-3 text-sm">
                <p className="font-medium">API key generada. Se muestra solo una vez.</p>
                <code className="mt-2 block break-all rounded bg-background px-2 py-1">{latestApiKey}</code>
              </div>
            ) : null}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Scopes</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead>Último uso</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(integrationClients.data ?? []).map((client) => (
                  <TableRow key={client.id}>
                    <TableCell>{client.name}</TableCell>
                    <TableCell>{client.scopes_json.join(", ")}</TableCell>
                    <TableCell>
                      <Badge variant={client.is_active ? "success" : "secondary"}>{client.is_active ? "Activo" : "Inactivo"}</Badge>
                    </TableCell>
                    <TableCell>{client.last_used_at ? new Date(client.last_used_at).toLocaleString() : "-"}</TableCell>
                    <TableCell className="text-right">
                      <Button type="button" variant="outline" size="sm" onClick={() => rotateIntegrationClientKey.mutate(client.id)}>
                        Rotar key
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="rounded-md border p-3">
              <div className="mb-3">
                <p className="text-sm font-medium">Sandbox de tools</p>
                <p className="text-xs text-muted-foreground">Ejecuta una tool como la vería la IA externa, con redacciones y fuentes.</p>
              </div>
              <form
                className="grid gap-2 lg:grid-cols-[140px_180px_220px_1fr_auto]"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (Number(sandboxClientId) > 0 && sandboxTechnicianId.trim() && sandboxTool.trim()) runIntegrationSandbox.mutate()
                }}
              >
                <select className="h-9 rounded-md border bg-background px-3 text-sm" value={sandboxClientId} onChange={(event) => setSandboxClientId(event.target.value)}>
                  <option value="">Cliente</option>
                  {(integrationClients.data ?? []).map((client) => (
                    <option key={client.id} value={client.id}>
                      {client.name}
                    </option>
                  ))}
                </select>
                <Input value={sandboxTechnicianId} onChange={(event) => setSandboxTechnicianId(event.target.value)} placeholder="Técnico" />
                <Input value={sandboxTool} onChange={(event) => setSandboxTool(event.target.value)} placeholder="Tool" />
                <Input value={sandboxArguments} onChange={(event) => setSandboxArguments(event.target.value)} placeholder='{"budget_number":"2026/143"}' />
                <Button disabled={runIntegrationSandbox.isPending}>Probar</Button>
              </form>
              {runIntegrationSandbox.data ? (
                <pre className="mt-3 max-h-72 overflow-auto rounded-md bg-muted p-3 text-xs">{JSON.stringify(runIntegrationSandbox.data, null, 2)}</pre>
              ) : null}
              {runIntegrationSandbox.isError ? <p className="mt-2 text-sm text-destructive">{runIntegrationSandbox.error.message}</p> : null}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "hoteles" ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Cadenas</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <form
                className="flex gap-2"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (chainName.trim()) createChain.mutate()
                }}
              >
                <Input value={chainName} onChange={(event) => setChainName(event.target.value)} placeholder="Nombre de cadena" />
                <Button disabled={createChain.isPending}>Crear</Button>
              </form>
              <SimpleTable rows={(chains.data ?? []).map((chain) => [chain.name, chain.is_active ? "Activa" : "Inactiva"])} headings={["Cadena", "Estado"]} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Hoteles</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <form
                className="grid gap-2 md:grid-cols-[1fr_1fr_100px_auto]"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (hotelName.trim() && hotelChainId) createHotel.mutate()
                }}
              >
                <select className="h-9 rounded-md border bg-background px-3 text-sm" value={hotelChainId} onChange={(event) => setHotelChainId(event.target.value)}>
                  <option value="">Cadena</option>
                  {(chains.data ?? []).map((chain) => (
                    <option key={chain.id} value={chain.id}>
                      {chain.name}
                    </option>
                  ))}
                </select>
                <Input value={hotelName} onChange={(event) => setHotelName(event.target.value)} placeholder="Hotel" />
                <Input value={hotelCode} onChange={(event) => setHotelCode(event.target.value)} placeholder="Código" />
                <Button disabled={createHotel.isPending}>Crear</Button>
              </form>
              <SimpleTable
                headings={["Hotel", "Cadena", "Código"]}
                rows={(hotels.data ?? []).map((hotel) => [
                  hotel.name,
                  chains.data?.find((chain) => chain.id === hotel.chain_id)?.name ?? String(hotel.chain_id),
                  hotel.code ?? "-",
                ])}
              />
            </CardContent>
          </Card>
        </div>
      ) : null}

      {activeTab === "reglas" ? (
        <Card>
          <CardHeader>
            <CardTitle>Reglas de carpetas</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <form
              className="grid gap-2 lg:grid-cols-[1fr_1.4fr_180px_180px_1fr_auto]"
              onSubmit={(event) => {
                event.preventDefault()
                if (rulePattern.trim()) createFolderRule.mutate()
              }}
            >
              <Input value={ruleName} onChange={(event) => setRuleName(event.target.value)} placeholder="Nombre" />
              <Input value={rulePattern} onChange={(event) => setRulePattern(event.target.value)} placeholder="/presupuestos/cadena/hotel/" />
              <select className="h-9 rounded-md border bg-background px-3 text-sm" value={ruleChainId} onChange={(event) => setRuleChainId(event.target.value)}>
                <option value="">Cadena</option>
                {(chains.data ?? []).map((chain) => (
                  <option key={chain.id} value={chain.id}>
                    {chain.name}
                  </option>
                ))}
              </select>
              <select className="h-9 rounded-md border bg-background px-3 text-sm" value={ruleHotelId} onChange={(event) => setRuleHotelId(event.target.value)}>
                <option value="">Hotel</option>
                {(hotels.data ?? []).map((hotel) => (
                  <option key={hotel.id} value={hotel.id}>
                    {hotel.name}
                  </option>
                ))}
              </select>
              <Input value={ruleTags} onChange={(event) => setRuleTags(event.target.value)} placeholder="tags separados por coma" />
              <Button disabled={createFolderRule.isPending}>Crear</Button>
            </form>
            <Button type="button" variant="outline" onClick={() => applyFolderRules.mutate()} disabled={applyFolderRules.isPending}>
              <RefreshCw data-icon="inline-start" />
              Reaplicar reglas
            </Button>
            {applyFolderRules.data ? (
              <p className="text-sm text-muted-foreground">
                Asignados: {applyFolderRules.data.assigned}. Cuarentena: {applyFolderRules.data.quarantined}. Omitidos: {applyFolderRules.data.skipped}.
              </p>
            ) : null}
            <SimpleTable
              headings={["Patrón", "Cadena", "Hotel", "Tags", "Estado"]}
              rows={(folderRules.data ?? []).map((rule) => [
                rule.pattern,
                chains.data?.find((chain) => chain.id === rule.chain_id)?.name ?? "-",
                hotels.data?.find((hotel) => hotel.id === rule.hotel_id)?.name ?? "-",
                rule.tags_json.join(", ") || "-",
                rule.is_active ? "Activa" : "Inactiva",
              ])}
            />
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "grupos" ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Perfiles y grupos</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <form
                className="grid gap-2"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (groupName.trim()) createAccessGroup.mutate()
                }}
              >
                <Input value={groupName} onChange={(event) => setGroupName(event.target.value)} placeholder="Nombre del grupo" />
                <div className={tenantAdminEnabled ? "grid gap-2 md:grid-cols-3" : "grid gap-2"}>
                  {tenantAdminEnabled ? (
                    <>
                      <Input value={groupChainIds} onChange={(event) => setGroupChainIds(event.target.value)} placeholder="IDs cadena: 1,2" />
                      <Input value={groupHotelIds} onChange={(event) => setGroupHotelIds(event.target.value)} placeholder="IDs hotel: 3,4" />
                    </>
                  ) : null}
                  <Input value={groupDeniedTags} onChange={(event) => setGroupDeniedTags(event.target.value)} placeholder="tags bloqueados" />
                </div>
                <div className="flex flex-wrap gap-3 text-sm">
                  {tenantAdminEnabled ? (
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={groupAllowAll} onChange={(event) => setGroupAllowAll(event.target.checked)} />
                      Todos los hoteles
                    </label>
                  ) : null}
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={groupCanPrices} onChange={(event) => setGroupCanPrices(event.target.checked)} />
                    Ver precios
                  </label>
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={groupCanSearchBudgets} onChange={(event) => setGroupCanSearchBudgets(event.target.checked)} />
                    Buscar presupuestos
                  </label>
                </div>
                <Button disabled={createAccessGroup.isPending}>Crear grupo</Button>
              </form>
              <SimpleTable
                headings={["Grupo", "Permisos", "Tags bloqueados"]}
                rows={(accessGroups.data ?? []).map((group) => [
                  group.name,
                  [
                    group.permissions_json.can_view_prices ? "precios" : "sin precios",
                    group.permissions_json.can_search_budgets ? "busca presupuestos" : "busqueda limitada",
                    tenantAdminEnabled ? (group.permissions_json.allow_all_hotels ? "todos hoteles" : `hoteles: ${String(group.permissions_json.hotel_ids ?? "[]")}`) : null,
                  ].filter(Boolean).join(" · "),
                  String(group.permissions_json.denied_tags ?? "[]"),
                ])}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Asignar miembros</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <form
                className="grid gap-2"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (memberGroupId && memberPrincipalId.trim()) upsertMember.mutate()
                }}
              >
                <select className="h-9 rounded-md border bg-background px-3 text-sm" value={memberGroupId} onChange={(event) => setMemberGroupId(event.target.value)}>
                  <option value="">Grupo</option>
                  {(accessGroups.data ?? []).map((group) => (
                    <option key={group.id} value={group.id}>
                      {group.name}
                    </option>
                  ))}
                </select>
                <select className="h-9 rounded-md border bg-background px-3 text-sm" value={memberType} onChange={(event) => setMemberType(event.target.value as "user" | "technician")}>
                  <option value="technician">Técnico externo</option>
                  <option value="user">Usuario interno</option>
                </select>
                <Input value={memberPrincipalId} onChange={(event) => setMemberPrincipalId(event.target.value)} placeholder="ID técnico o ID usuario" />
                <Button disabled={upsertMember.isPending}>Asignar</Button>
              </form>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {activeTab === "cuarentena" ? (
        <Card>
          <CardHeader>
            <CardTitle>Documentos en cuarentena</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <form
              className="grid gap-2 lg:grid-cols-[120px_180px_180px_1fr_auto]"
              onSubmit={(event) => {
                event.preventDefault()
                if (assignDocumentId) updateDocumentAccess.mutate()
              }}
            >
              <Input value={assignDocumentId} onChange={(event) => setAssignDocumentId(event.target.value)} placeholder="Doc ID" />
              <select className="h-9 rounded-md border bg-background px-3 text-sm" value={assignChainId} onChange={(event) => setAssignChainId(event.target.value)}>
                <option value="">Cadena</option>
                {(chains.data ?? []).map((chain) => (
                  <option key={chain.id} value={chain.id}>
                    {chain.name}
                  </option>
                ))}
              </select>
              <select className="h-9 rounded-md border bg-background px-3 text-sm" value={assignHotelId} onChange={(event) => setAssignHotelId(event.target.value)}>
                <option value="">Hotel</option>
                {(hotels.data ?? []).map((hotel) => (
                  <option key={hotel.id} value={hotel.id}>
                    {hotel.name}
                  </option>
                ))}
              </select>
              <Input value={assignTags} onChange={(event) => setAssignTags(event.target.value)} placeholder="tags manuales" />
              <Button disabled={updateDocumentAccess.isPending}>Asignar</Button>
            </form>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Documento</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Origen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(quarantine.data ?? []).map((document) => (
                  <TableRow key={document.id}>
                    <TableCell>{document.id}</TableCell>
                    <TableCell>{document.original_filename}</TableCell>
                    <TableCell>{document.document_type}</TableCell>
                    <TableCell className="max-w-[360px] truncate">{document.source_path ?? "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      {activeTab === "tags" ? (
        <Card>
          <CardHeader>
            <CardTitle>Tags sensibles</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <form
              className="grid gap-2 md:grid-cols-[220px_1fr_auto]"
              onSubmit={(event) => {
                event.preventDefault()
                if (tagName.trim()) createSensitiveTag.mutate()
              }}
            >
              <Input value={tagName} onChange={(event) => setTagName(event.target.value)} placeholder="contabilidad" />
              <Input value={tagDescription} onChange={(event) => setTagDescription(event.target.value)} placeholder="Descripción" />
              <Button disabled={createSensitiveTag.isPending}>Crear tag</Button>
            </form>
            <SimpleTable headings={["Tag", "Descripción", "Estado"]} rows={(sensitiveTags.data ?? []).map((tag) => [tag.name, tag.description ?? "-", tag.is_active ? "Activo" : "Inactivo"])} />
          </CardContent>
        </Card>
      ) : null}
    </>
  )
}

function OperationalTab({
  auditLogs,
  alerts,
  metrics,
  systemHealth,
  queueStatus,
  operationsOverview,
  operationsStatus,
  maintenanceReport,
  productionChecklist,
  productionReadiness,
  storageIntegrity,
  qualityRules,
  qualitySummary,
  operationsDocuments,
  watchedFiles,
  ingestionEvents,
  stats,
  status,
  setStatus,
  documentType,
  setDocumentType,
  sourcePath,
  setSourcePath,
  mode,
  setMode,
  reprocessPending,
  reprocessResult,
  reprocessError,
  onSubmit,
  pauseQueues,
  resumeQueues,
  explainPrincipalType,
  setExplainPrincipalType,
  explainPrincipalId,
  setExplainPrincipalId,
  explainDocumentId,
  setExplainDocumentId,
  explainAccess,
  graphDocumentId,
  setGraphDocumentId,
  loadDocumentGraph,
  rulePreviewPath,
  setRulePreviewPath,
  rulePreviewPattern,
  setRulePreviewPattern,
  rulePreviewTags,
  setRulePreviewTags,
  previewRule,
  redactionPrincipalType,
  setRedactionPrincipalType,
  redactionPrincipalId,
  setRedactionPrincipalId,
  redactionText,
  setRedactionText,
  previewRedaction,
  recalculateQuality,
  bulkTagDocumentIds,
  setBulkTagDocumentIds,
  bulkTagAdd,
  setBulkTagAdd,
  bulkTagRemove,
  setBulkTagRemove,
  applyBulkTags,
}: any) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Control de ingesta</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-[1fr_auto_auto]">
            <div className="text-sm">
              <div className="flex flex-wrap gap-2">
                <Badge variant={queueStatus?.ingestion_paused ? "warning" : "success"}>
                  {queueStatus?.ingestion_paused ? "Ingesta pausada" : "Ingesta activa"}
                </Badge>
                <Badge variant={queueStatus?.backpressure_active ? "warning" : "outline"}>
                  Pendientes: {queueStatus?.pending_jobs ?? 0}/{queueStatus?.max_pending_jobs ?? "-"}
                </Badge>
                <Badge variant="outline">Procesando: {queueStatus?.processing_jobs ?? 0}</Badge>
              </div>
              <p className="mt-2 text-muted-foreground">Controla el watchdog y los escaneos masivos sin parar la aplicación.</p>
            </div>
            <Button type="button" variant="outline" onClick={() => pauseQueues.mutate()} disabled={pauseQueues.isPending || queueStatus?.ingestion_paused}>
              <Pause data-icon="inline-start" />
              Pausar
            </Button>
            <Button type="button" variant="outline" onClick={() => resumeQueues.mutate()} disabled={resumeQueues.isPending || !queueStatus?.ingestion_paused}>
              <Play data-icon="inline-start" />
              Reanudar
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Centro de operaciones</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm md:grid-cols-4">
            <MetricTile label="GB procesados" value={formatGigabytes(operationsOverview?.documents?.total_size_bytes ?? 0)} />
            <MetricTile label="OCR bajo" value={String(operationsOverview?.documents?.low_ocr_pages ?? 0)} />
            <MetricTile label="Pendiente/procesando" value={String(operationsOverview?.jobs?.pending_or_processing ?? 0)} />
            <MetricTile label="ETA" value={formatDuration(operationsOverview?.jobs?.estimated_remaining_seconds)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Checklist producción</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm md:grid-cols-2">
            {(productionChecklist?.items ?? []).map((item: any) => (
              <div key={item.key} className="rounded-md border p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium">{item.title}</p>
                  <Badge variant={item.status === "ok" ? "success" : item.status === "error" ? "destructive" : "warning"}>{item.status}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{item.description}</p>
              </div>
            ))}
            {!productionChecklist?.items?.length ? <p className="text-muted-foreground">Sin datos de checklist.</p> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between gap-3">
            <CardTitle>Readiness producción</CardTitle>
            <Badge variant={productionReadiness?.status === "ready" ? "success" : "warning"}>{productionReadiness?.status ?? "sin datos"}</Badge>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm md:grid-cols-2">
            {(productionReadiness?.checks ?? []).map((check: any) => (
              <div key={check.key} className="rounded-md border p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium">{check.key}</p>
                  <Badge variant={check.status === "ok" ? "success" : check.status === "error" ? "destructive" : "warning"}>{check.status}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{check.description}</p>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between gap-3">
            <CardTitle>Calidad de datos</CardTitle>
            <Button type="button" variant="outline" size="sm" onClick={() => recalculateQuality.mutate()} disabled={recalculateQuality.isPending}>
              <RefreshCw data-icon="inline-start" />
              Recalcular
            </Button>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="grid gap-2 md:grid-cols-3">
              {Object.entries(qualitySummary?.rules ?? {}).map(([key, value]: any) => (
                <div key={key} className="rounded-md border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-medium">{key}</p>
                    <Badge variant={value.count > 0 ? "warning" : "outline"}>{value.count}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{value.description}</p>
                </div>
              ))}
            </div>
            <MetricBlock title="Estados de calidad" values={qualitySummary?.by_quality_status} />
            <p className="text-xs text-muted-foreground">Umbral OCR bajo: {qualityRules?.low_ocr_threshold != null ? Math.round(qualityRules.low_ocr_threshold * 100) + "%" : "-"}</p>
            {recalculateQuality.data ? (
              <p className="text-sm text-muted-foreground">
                Recalculados: {recalculateQuality.data.updated}. En revisión: {recalculateQuality.data.needs_review}.
              </p>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Alertas avanzadas</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {alerts.map((alert: any) => (
              <div key={alert.key} className="flex items-start justify-between gap-3 rounded-md border p-3 text-sm">
                <div>
                  <div className="flex items-center gap-2">
                    <Badge variant={alert.severity === "critical" ? "destructive" : alert.severity === "warning" ? "warning" : "secondary"}>{alert.count}</Badge>
                    <p className="font-medium">{alert.title}</p>
                  </div>
                  <p className="mt-1 text-muted-foreground">{alert.description}</p>
                </div>
                <Button asChild variant="outline" size="sm">
                  <Link to={alert.action_url}>Abrir</Link>
                </Button>
              </div>
            ))}
            {!alerts.length ? <p className="text-sm text-muted-foreground">Sin alertas operativas activas.</p> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Reprocesado avanzado</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="grid gap-3 md:grid-cols-5" onSubmit={onSubmit}>
              <select className="h-9 rounded-md border bg-background px-3 text-sm" value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="failed">Fallidos</option>
                <option value="needs_review">Revisión</option>
                <option value="processed">Procesados</option>
                <option value="pending">Pendientes</option>
                <option value="">Cualquier estado</option>
              </select>
              <select className="h-9 rounded-md border bg-background px-3 text-sm" value={documentType} onChange={(event) => setDocumentType(event.target.value)}>
                <option value="">Cualquier tipo</option>
                <option value="presupuesto">Presupuesto</option>
                <option value="pedido">Pedido</option>
                <option value="factura">Factura</option>
                <option value="plano">Plano</option>
                <option value="imagen">Imagen</option>
                <option value="excel">Excel</option>
              </select>
              <Input value={sourcePath} onChange={(event) => setSourcePath(event.target.value)} placeholder="Carpeta contiene..." />
              <select className="h-9 rounded-md border bg-background px-3 text-sm" value={mode} onChange={(event) => setMode(event.target.value)}>
                <option value="full">Completo</option>
                <option value="ocr">OCR</option>
                <option value="classification">Clasificación</option>
                <option value="embeddings">Embeddings</option>
              </select>
              <Button disabled={reprocessPending || (!status && !documentType && !sourcePath)}>
                <RefreshCw data-icon="inline-start" />
                Reprocesar
              </Button>
            </form>
            {reprocessResult ? (
              <p className="mt-3 text-sm text-muted-foreground">
                Documentos encontrados: {reprocessResult.matched}. Jobs encolados: {reprocessResult.enqueued}.
              </p>
            ) : null}
            {reprocessError ? <p className="mt-3 text-sm text-destructive">{reprocessError}</p> : null}
          </CardContent>
        </Card>

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Simulador de acceso</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <form
                className="grid gap-2"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (explainPrincipalId.trim() && Number(explainDocumentId) > 0) explainAccess.mutate()
                }}
              >
                <select className="h-9 rounded-md border bg-background px-3 text-sm" value={explainPrincipalType} onChange={(event) => setExplainPrincipalType(event.target.value as "user" | "technician")}>
                  <option value="technician">Técnico externo</option>
                  <option value="user">Usuario interno</option>
                </select>
                <div className="grid gap-2 md:grid-cols-[1fr_120px_auto]">
                  <Input value={explainPrincipalId} onChange={(event) => setExplainPrincipalId(event.target.value)} placeholder="ID principal" />
                  <Input value={explainDocumentId} onChange={(event) => setExplainDocumentId(event.target.value)} placeholder="Doc ID" />
                  <Button disabled={explainAccess.isPending}>Comprobar</Button>
                </div>
              </form>
              {explainAccess.data ? (
                <div className="rounded-md border p-3 text-sm">
                  <Badge variant={explainAccess.data.allowed ? "success" : "destructive"}>{explainAccess.data.allowed ? "Permitido" : "Denegado"}</Badge>
                  <ul className="mt-2 space-y-1 text-muted-foreground">
                    {explainAccess.data.reasons.map((reason: string) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {explainAccess.isError ? <p className="text-sm text-destructive">{explainAccess.error.message}</p> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Grafo documental</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <form
                className="grid gap-2 md:grid-cols-[1fr_auto]"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (Number(graphDocumentId) > 0) loadDocumentGraph.mutate()
                }}
              >
                <Input value={graphDocumentId} onChange={(event) => setGraphDocumentId(event.target.value)} placeholder="Doc ID" />
                <Button disabled={loadDocumentGraph.isPending}>
                  <Network data-icon="inline-start" />
                  Cargar
                </Button>
              </form>
              {loadDocumentGraph.data ? (
                <div className="space-y-2 text-sm">
                  <MetricBlock title="Nodos" values={{ documentos: loadDocumentGraph.data.nodes.length }} />
                  <MetricBlock title="Relaciones" values={{ enlaces: loadDocumentGraph.data.edges.length }} />
                  <div className="max-h-40 overflow-auto rounded-md border">
                    <Table>
                      <TableBody>
                        {loadDocumentGraph.data.edges.map((edge: any, index: number) => (
                          <TableRow key={`${edge.from_document_id}-${edge.to_document_id}-${edge.relation}-${index}`}>
                            <TableCell>{edge.relation}</TableCell>
                            <TableCell>
                              {edge.from_document_id} {"->"} {edge.to_document_id}
                            </TableCell>
                            <TableCell>{edge.label ?? "-"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              ) : null}
              {loadDocumentGraph.isError ? <p className="text-sm text-destructive">{loadDocumentGraph.error.message}</p> : null}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Auditoría reciente</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Acción</TableHead>
                  <TableHead>Entidad</TableHead>
                  <TableHead>Usuario</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {auditLogs.slice(0, 12).map((log: any) => (
                  <TableRow key={log.id}>
                    <TableCell>{new Date(log.created_at).toLocaleString()}</TableCell>
                    <TableCell>{log.action}</TableCell>
                    <TableCell>
                      {log.entity_type ?? "-"} {log.entity_id ?? ""}
                    </TableCell>
                    <TableCell>{log.user_id ?? "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Estado operativo</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div>
              <p className="mb-1 font-medium">Salud del sistema</p>
              <div className="flex flex-wrap gap-2">
                <Badge variant={systemHealth?.status === "ok" ? "success" : "warning"}>{systemHealth?.status ?? "sin datos"}</Badge>
                {Object.entries(systemHealth?.checks ?? {}).map(([key, check]: any) => (
                  <Badge key={key} variant={check.status === "ok" ? "outline" : "warning"}>
                    {key}: {check.status}
                  </Badge>
                ))}
              </div>
            </div>
            <MetricBlock title="Jobs" values={operationsStatus?.jobs_by_status} />
            <MetricBlock title="Calidad documental" values={operationsOverview?.documents?.by_quality_status} />
            <MetricBlock title="Colas" values={queueStatus?.queues ? Object.fromEntries(Object.entries(queueStatus.queues).map(([key, value]: any) => [key, value.pending ?? 0])) : undefined} />
            <MetricBlock title="Watchdog" values={operationsStatus?.watched_files_by_status} />
            <MetricBlock title="Eventos" values={operationsStatus?.ingestion_events_by_type} />
            <div className="grid gap-2 text-muted-foreground">
              {maintenanceReport?.checks.map((check: any) => (
                <div key={check.key} className="flex items-center justify-between rounded-md border px-2 py-1">
                  <span>{check.key}</span>
                  <Badge variant={check.status === "ok" ? "success" : "warning"}>{check.count}</Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Integridad de ficheros</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <MetricTile label="BD comprobados" value={String(storageIntegrity?.checked_documents ?? 0)} />
              <MetricTile label="Sin fichero" value={String(storageIntegrity?.missing_files ?? 0)} />
              <MetricTile label="Huérfanos" value={String(storageIntegrity?.orphan_files ?? 0)} />
              <MetricTile label="Hash dudoso" value={String(storageIntegrity?.hash_mismatches ?? 0)} />
            </div>
            {(storageIntegrity?.missing_file_samples ?? []).length ? (
              <pre className="max-h-28 overflow-auto rounded-md bg-muted p-2 text-xs">{JSON.stringify(storageIntegrity?.missing_file_samples, null, 2)}</pre>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Tags en lote</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <form
              className="grid gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                if (ids(bulkTagDocumentIds).length) applyBulkTags.mutate()
              }}
            >
              <Input value={bulkTagDocumentIds} onChange={(event) => setBulkTagDocumentIds(event.target.value)} placeholder="IDs documento: 12,15,18" />
              <Input value={bulkTagAdd} onChange={(event) => setBulkTagAdd(event.target.value)} placeholder="Añadir tags" />
              <Input value={bulkTagRemove} onChange={(event) => setBulkTagRemove(event.target.value)} placeholder="Quitar tags" />
              <Button disabled={applyBulkTags.isPending}>Aplicar tags</Button>
            </form>
            {applyBulkTags.data ? <p className="text-muted-foreground">Actualizados: {applyBulkTags.data.updated}</p> : null}
            {applyBulkTags.isError ? <p className="text-sm text-destructive">{applyBulkTags.error.message}</p> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Preview reglas</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <form
              className="grid gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                if (rulePreviewPath.trim() && rulePreviewPattern.trim()) previewRule.mutate()
              }}
            >
              <Input value={rulePreviewPath} onChange={(event) => setRulePreviewPath(event.target.value)} placeholder="Ruta de archivo" />
              <Input value={rulePreviewPattern} onChange={(event) => setRulePreviewPattern(event.target.value)} placeholder="/presupuestos/" />
              <Input value={rulePreviewTags} onChange={(event) => setRulePreviewTags(event.target.value)} placeholder="tags separados por coma" />
              <Button disabled={previewRule.isPending}>Probar regla</Button>
            </form>
            {previewRule.data ? (
              <div className="rounded-md border p-2">
                <Badge variant={previewRule.data.matches ? "success" : "warning"}>{previewRule.data.matches ? "Coincide" : "No coincide"}</Badge>
                <p className="mt-2 text-xs text-muted-foreground">{previewRule.data.normalized_path}</p>
              </div>
            ) : null}
            {previewRule.isError ? <p className="text-sm text-destructive">{previewRule.error.message}</p> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Preview redacción</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <form
              className="grid gap-2"
              onSubmit={(event) => {
                event.preventDefault()
                if (redactionPrincipalId.trim() && redactionText.trim()) previewRedaction.mutate()
              }}
            >
              <select className="h-9 rounded-md border bg-background px-3 text-sm" value={redactionPrincipalType} onChange={(event) => setRedactionPrincipalType(event.target.value as "user" | "technician")}>
                <option value="technician">Técnico</option>
                <option value="user">Usuario</option>
              </select>
              <Input value={redactionPrincipalId} onChange={(event) => setRedactionPrincipalId(event.target.value)} placeholder="ID principal" />
              <Input value={redactionText} onChange={(event) => setRedactionText(event.target.value)} placeholder="Texto con importes" />
              <Button disabled={previewRedaction.isPending}>Ver redacción</Button>
            </form>
            {previewRedaction.data ? (
              <div className="rounded-md border p-2">
                <Badge variant={previewRedaction.data.can_view_prices ? "warning" : "success"}>
                  {previewRedaction.data.can_view_prices ? "Ve precios" : "Precios ocultos"}
                </Badge>
                <p className="mt-2 text-xs leading-5">{previewRedaction.data.redacted_text}</p>
              </div>
            ) : null}
            {previewRedaction.isError ? <p className="text-sm text-destructive">{previewRedaction.error.message}</p> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Disco y cola de entrada</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <DiskLine label="Entrada" usage={operationsStatus?.disk?.input_dir} />
            <DiskLine label="Originales" usage={operationsStatus?.disk?.files_dir} />
            <div className="max-h-40 overflow-auto rounded-md border">
              <Table>
                <TableBody>
                  {watchedFiles.slice(0, 8).map((file: any) => (
                    <TableRow key={file.id}>
                      <TableCell>
                        <Badge variant={file.status === "failed" ? "destructive" : file.status === "processed" ? "success" : "outline"}>{file.status}</Badge>
                      </TableCell>
                      <TableCell className="max-w-[260px] truncate">{file.path}</TableCell>
                      <TableCell>{file.document_id ?? "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Eventos recientes</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="max-h-48 overflow-auto rounded-md border">
              <Table>
                <TableBody>
                  {ingestionEvents.slice(0, 10).map((event: any) => (
                    <TableRow key={event.id}>
                      <TableCell>
                        <Activity className="size-4 text-muted-foreground" />
                      </TableCell>
                      <TableCell>{event.event_type}</TableCell>
                      <TableCell className="max-w-[260px] truncate">{event.source_path ?? "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Carpetas vigiladas</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            {inputFolders.map((folder) => (
              <code key={folder} className="rounded-md bg-muted px-2 py-1">
                {folder}
              </code>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Configuración IA/OCR</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm text-muted-foreground">
            <span>AI_PROVIDER=local_openai_compatible</span>
            <span>AI_BASE_URL configurado solo en backend</span>
            <span>OCR_ENGINE=paddleocr</span>
            <span>Documentos con revisión: {stats?.documents_needs_review ?? "-"}</span>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Rendimiento y volumen</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <MetricBlock title="Documentos por estado" values={metrics?.documents_by_status} />
            <MetricBlock title="Documentos por tipo" values={metrics?.documents_by_type} />
            <MetricBlock title="Jobs por estado" values={metrics?.jobs_by_status} />
            <div className="rounded-md border">
              <Table>
                <TableBody>
                  {(operationsDocuments?.items ?? []).slice(0, 8).map((document: any) => (
                    <TableRow key={document.id}>
                      <TableCell>{document.id}</TableCell>
                      <TableCell className="max-w-[200px] truncate">{document.original_filename}</TableCell>
                      <TableCell>{document.status}</TableCell>
                      <TableCell>{document.quality_status}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <p className="text-xs text-muted-foreground">Documentos paginados: {operationsDocuments?.total ?? 0}</p>
            <div className="flex items-center gap-2 text-muted-foreground">
              <ShieldCheck className="size-4" />
              Eventos auditados: {metrics?.audit_events_total ?? "-"}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function SimpleTable({ headings, rows }: { headings: string[]; rows: string[][] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {headings.map((heading) => (
            <TableHead key={heading}>{heading}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow key={index}>
            {row.map((cell, cellIndex) => (
              <TableCell key={cellIndex}>{cell}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function MetricBlock({ title, values }: { title: string; values?: Record<string, number> }) {
  return (
    <div>
      <p className="mb-1 font-medium">{title}</p>
      <div className="flex flex-wrap gap-2">
        {Object.entries(values ?? {}).map(([key, value]) => (
          <Badge key={key} variant="outline">
            {key}: {value}
          </Badge>
        ))}
        {!Object.keys(values ?? {}).length ? <span className="text-muted-foreground">Sin datos</span> : null}
      </div>
    </div>
  )
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
    </div>
  )
}

function ConfigStatus({ label, value, tone }: { label: string; value: string; tone: BadgeProps["variant"] }) {
  return (
    <div className="rounded-md border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-2">
        <Badge variant={tone}>{value}</Badge>
      </div>
    </div>
  )
}

function DiskLine({ label, usage }: { label: string; usage?: { path: string; total: number; used: number; free: number } }) {
  const usedPercent = usage?.total ? Math.round((usage.used / usage.total) * 100) : 0
  return (
    <div className="rounded-md border p-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 font-medium">
          <HardDrive className="size-4 text-muted-foreground" />
          {label}
        </span>
        <span className="text-muted-foreground">{usedPercent}% usado</span>
      </div>
      <div className="h-2 overflow-hidden rounded bg-muted">
        <div className="h-full bg-primary" style={{ width: `${Math.min(usedPercent, 100)}%` }} />
      </div>
      <p className="mt-1 truncate text-xs text-muted-foreground">{usage?.path ?? "-"}</p>
    </div>
  )
}

function formatGigabytes(bytes: number) {
  return (bytes / 1024 / 1024 / 1024).toFixed(2)
}

function formatDuration(seconds?: number | null) {
  if (seconds == null) return "-"
  if (seconds < 60) return Math.round(seconds) + "s"
  if (seconds < 3600) return Math.round(seconds / 60) + "min"
  return (seconds / 3600).toFixed(1) + "h"
}

function optionalId(value: string) {
  const numeric = Number(value)
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null
}

function ids(value: string) {
  return value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item) && item > 0)
}

function csv(value: string) {
  return value
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
}

function parseJsonObject(value: string) {
  const parsed = JSON.parse(value || "{}")
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Los argumentos deben ser un objeto JSON")
  }
  return parsed as Record<string, unknown>
}
