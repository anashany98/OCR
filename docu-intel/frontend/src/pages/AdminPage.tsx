import { FormEvent, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Activity, Building2, FolderCog, HardDrive, Network, RefreshCw, ShieldCheck, Tags, Users } from "lucide-react"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { Badge } from "@/components/ui/badge"
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

type AdminTab = "operativa" | "hoteles" | "reglas" | "grupos" | "cuarentena" | "tags"

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

  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats })
  const alerts = useQuery({ queryKey: ["alerts"], queryFn: api.alerts })
  const metrics = useQuery({ queryKey: ["processing-metrics"], queryFn: api.processingMetrics })
  const operationsStatus = useQuery({ queryKey: ["operations-status"], queryFn: api.operationsStatus, refetchInterval: 5000 })
  const maintenanceReport = useQuery({ queryKey: ["maintenance-report"], queryFn: api.maintenanceReport, refetchInterval: 15000 })
  const watchedFiles = useQuery({ queryKey: ["watched-files"], queryFn: api.watchedFiles, refetchInterval: 5000 })
  const ingestionEvents = useQuery({ queryKey: ["ingestion-events"], queryFn: api.ingestionEvents, refetchInterval: 5000 })
  const auditLogs = useQuery({ queryKey: ["audit-logs"], queryFn: api.auditLogs })
  const chains = useQuery({ queryKey: ["hotel-chains"], queryFn: api.hotelChains })
  const hotels = useQuery({ queryKey: ["hotels"], queryFn: api.hotels })
  const folderRules = useQuery({ queryKey: ["folder-rules"], queryFn: api.folderRules })
  const quarantine = useQuery({ queryKey: ["quarantine-documents"], queryFn: api.quarantineDocuments })
  const accessGroups = useQuery({ queryKey: ["access-groups"], queryFn: api.accessGroups })
  const sensitiveTags = useQuery({ queryKey: ["sensitive-tags"], queryFn: api.sensitiveTags })

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
          chain_ids: ids(groupChainIds),
          hotel_ids: ids(groupHotelIds),
          allow_all_hotels: groupAllowAll,
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

  function invalidate(keys: string[]) {
    keys.forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }))
  }

  function onReprocessSubmit(event: FormEvent) {
    event.preventDefault()
    reprocess.mutate()
  }

  return (
    <>
      <PageHeader title="Administración" description="Gobierno documental, aislamiento por hotel, políticas y auditoría." />
      <div className="mb-4 flex flex-wrap gap-2">
        {[
          ["operativa", "Operativa", ShieldCheck],
          ["hoteles", "Cadenas/Hoteles", Building2],
          ["reglas", "Reglas de carpetas", FolderCog],
          ["grupos", "Perfiles/Grupos", Users],
          ["cuarentena", "Cuarentena", ShieldCheck],
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
          operationsStatus={operationsStatus.data}
          maintenanceReport={maintenanceReport.data}
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
        />
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
                <div className="grid gap-2 md:grid-cols-3">
                  <Input value={groupChainIds} onChange={(event) => setGroupChainIds(event.target.value)} placeholder="IDs cadena: 1,2" />
                  <Input value={groupHotelIds} onChange={(event) => setGroupHotelIds(event.target.value)} placeholder="IDs hotel: 3,4" />
                  <Input value={groupDeniedTags} onChange={(event) => setGroupDeniedTags(event.target.value)} placeholder="tags bloqueados" />
                </div>
                <div className="flex flex-wrap gap-3 text-sm">
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={groupAllowAll} onChange={(event) => setGroupAllowAll(event.target.checked)} />
                    Todos los hoteles
                  </label>
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
                headings={["Grupo", "Scope", "Tags bloqueados"]}
                rows={(accessGroups.data ?? []).map((group) => [
                  group.name,
                  group.permissions_json.allow_all_hotels ? "Todos" : `Hoteles: ${String(group.permissions_json.hotel_ids ?? "[]")}`,
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
  operationsStatus,
  maintenanceReport,
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
}: any) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
      <div className="space-y-4">
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
            <MetricBlock title="Jobs" values={operationsStatus?.jobs_by_status} />
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
            <CardTitle>Métricas de volumen</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <MetricBlock title="Documentos por estado" values={metrics?.documents_by_status} />
            <MetricBlock title="Documentos por tipo" values={metrics?.documents_by_type} />
            <MetricBlock title="Jobs por estado" values={metrics?.jobs_by_status} />
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
