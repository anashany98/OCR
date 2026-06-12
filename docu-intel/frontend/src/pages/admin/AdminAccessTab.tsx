import type { FormEvent } from "react"
import { RefreshCw } from "lucide-react"

import type {
  AccessExplain,
  AccessGroup,
  AccessGroupMember,
  EffectiveAccess,
  FolderRule,
  Hotel,
  HotelChain,
  RedactionPreview,
  RulePreview,
  SensitiveTag,
} from "@/types/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

import { csv, ids, optionalId, SimpleTable } from "./shared"

interface MutationLike<TData = unknown> {
  mutate: () => void
  isPending: boolean
  data?: TData
  isError: boolean
  error: Error | null
}

interface ApplyFolderRulesMutation {
  mutate: () => void
  isPending: boolean
  data?: { matched: number; assigned: number; quarantined: number; skipped: number }
}

interface AdminAccessTabProps {
  chains: HotelChain[]
  hotels: Hotel[]
  folderRules: FolderRule[]
  accessGroups: AccessGroup[]
  sensitiveTags: SensitiveTag[]
  tenantAdminEnabled: boolean
  chainName: string
  setChainName: (v: string) => void
  hotelName: string
  setHotelName: (v: string) => void
  hotelCode: string
  setHotelCode: (v: string) => void
  hotelChainId: string
  setHotelChainId: (v: string) => void
  createChain: MutationLike
  createHotel: MutationLike
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
  memberGroupId: string
  setMemberGroupId: (v: string) => void
  memberType: "user" | "technician"
  setMemberType: (v: "user" | "technician") => void
  memberPrincipalId: string
  setMemberPrincipalId: (v: string) => void
  upsertMember: MutationLike
  explainPrincipalType: "user" | "technician"
  setExplainPrincipalType: (v: "user" | "technician") => void
  explainPrincipalId: string
  setExplainPrincipalId: (v: string) => void
  explainDocumentId: string
  setExplainDocumentId: (v: string) => void
  explainAccess: MutationLike<AccessExplain>
  rulePreviewPath: string
  setRulePreviewPath: (v: string) => void
  rulePreviewPattern: string
  setRulePreviewPattern: (v: string) => void
  rulePreviewTags: string
  setRulePreviewTags: (v: string) => void
  previewRule: MutationLike<RulePreview>
  redactionPrincipalType: "user" | "technician"
  setRedactionPrincipalType: (v: "user" | "technician") => void
  redactionPrincipalId: string
  setRedactionPrincipalId: (v: string) => void
  redactionText: string
  setRedactionText: (v: string) => void
  previewRedaction: MutationLike<RedactionPreview>
  tagName: string
  setTagName: (v: string) => void
  tagDescription: string
  setTagDescription: (v: string) => void
  createSensitiveTag: MutationLike
}

export function AdminAccessTab({
  chains,
  hotels,
  folderRules,
  accessGroups,
  sensitiveTags,
  tenantAdminEnabled,
  chainName,
  setChainName,
  hotelName,
  setHotelName,
  hotelCode,
  setHotelCode,
  hotelChainId,
  setHotelChainId,
  createChain,
  createHotel,
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
  createFolderRule,
  applyFolderRules,
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
  createAccessGroup,
  memberGroupId,
  setMemberGroupId,
  memberType,
  setMemberType,
  memberPrincipalId,
  setMemberPrincipalId,
  upsertMember,
  explainPrincipalType,
  setExplainPrincipalType,
  explainPrincipalId,
  setExplainPrincipalId,
  explainDocumentId,
  setExplainDocumentId,
  explainAccess,
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
  tagName,
  setTagName,
  tagDescription,
  setTagDescription,
  createSensitiveTag,
}: AdminAccessTabProps) {
  return (
    <div className="space-y-4">
      {tenantAdminEnabled ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Cadenas</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <form
                className="flex gap-2"
                onSubmit={(event: FormEvent) => {
                  event.preventDefault()
                  if (chainName.trim()) createChain.mutate()
                }}
              >
                <Input
                  value={chainName}
                  onChange={(event) => setChainName(event.target.value)}
                  placeholder="Nombre de cadena"
                />
                <Button disabled={createChain.isPending}>Crear</Button>
              </form>
              <SimpleTable
                rows={chains.map((chain) => [chain.name, chain.is_active ? "Activa" : "Inactiva"])}
                headings={["Cadena", "Estado"]}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Hoteles</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <form
                className="grid gap-2 md:grid-cols-[1fr_1fr_100px_auto]"
                onSubmit={(event: FormEvent) => {
                  event.preventDefault()
                  if (hotelName.trim() && hotelChainId) createHotel.mutate()
                }}
              >
                <select
                  className="h-9 rounded-md border bg-background px-3 text-sm"
                  value={hotelChainId}
                  onChange={(event) => setHotelChainId(event.target.value)}
                >
                  <option value="">Cadena</option>
                  {chains.map((chain) => (
                    <option key={chain.id} value={chain.id}>
                      {chain.name}
                    </option>
                  ))}
                </select>
                <Input
                  value={hotelName}
                  onChange={(event) => setHotelName(event.target.value)}
                  placeholder="Hotel"
                />
                <Input
                  value={hotelCode}
                  onChange={(event) => setHotelCode(event.target.value)}
                  placeholder="C&oacute;digo"
                />
                <Button disabled={createHotel.isPending}>Crear</Button>
              </form>
              <SimpleTable
                headings={["Hotel", "Cadena", "C&oacute;digo"]}
                rows={hotels.map((hotel) => [
                  hotel.name,
                  chains.find((chain) => chain.id === hotel.chain_id)?.name ??
                    String(hotel.chain_id),
                  hotel.code ?? "-",
                ])}
              />
            </CardContent>
          </Card>
        </div>
      ) : null}

      {tenantAdminEnabled ? (
        <Card>
          <CardHeader>
            <CardTitle>Reglas de carpetas</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <form
              className="grid gap-2 lg:grid-cols-[1fr_1.4fr_180px_180px_1fr_auto]"
              onSubmit={(event: FormEvent) => {
                event.preventDefault()
                if (rulePattern.trim()) createFolderRule.mutate()
              }}
            >
              <Input
                value={ruleName}
                onChange={(event) => setRuleName(event.target.value)}
                placeholder="Nombre"
              />
              <Input
                value={rulePattern}
                onChange={(event) => setRulePattern(event.target.value)}
                placeholder="/presupuestos/cadena/hotel/"
              />
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={ruleChainId}
                onChange={(event) => setRuleChainId(event.target.value)}
              >
                <option value="">Cadena</option>
                {chains.map((chain) => (
                  <option key={chain.id} value={chain.id}>
                    {chain.name}
                  </option>
                ))}
              </select>
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={ruleHotelId}
                onChange={(event) => setRuleHotelId(event.target.value)}
              >
                <option value="">Hotel</option>
                {hotels.map((hotel) => (
                  <option key={hotel.id} value={hotel.id}>
                    {hotel.name}
                  </option>
                ))}
              </select>
              <Input
                value={ruleTags}
                onChange={(event) => setRuleTags(event.target.value)}
                placeholder="tags separados por coma"
              />
              <Button disabled={createFolderRule.isPending}>Crear</Button>
            </form>
            <Button
              type="button"
              variant="outline"
              onClick={() => applyFolderRules.mutate()}
              disabled={applyFolderRules.isPending}
            >
              <RefreshCw data-icon="inline-start" />
              Reaplicar reglas
            </Button>
            {applyFolderRules.data ? (
              <p className="text-sm text-muted-foreground">
                Asignados: {applyFolderRules.data.assigned}. Cuarentena:{" "}
                {applyFolderRules.data.quarantined}. Omitidos: {applyFolderRules.data.skipped}.
              </p>
            ) : null}
            <SimpleTable
              headings={["Patr&oacute;n", "Cadena", "Hotel", "Tags", "Estado"]}
              rows={folderRules.map((rule) => [
                rule.pattern,
                chains.find((chain) => chain.id === rule.chain_id)?.name ?? "-",
                hotels.find((hotel) => hotel.id === rule.hotel_id)?.name ?? "-",
                rule.tags_json.join(", ") || "-",
                rule.is_active ? "Activa" : "Inactiva",
              ])}
            />
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Perfiles y grupos</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <form
              className="grid gap-2"
              onSubmit={(event: FormEvent) => {
                event.preventDefault()
                if (groupName.trim()) createAccessGroup.mutate()
              }}
            >
              <Input
                value={groupName}
                onChange={(event) => setGroupName(event.target.value)}
                placeholder="Nombre del grupo"
              />
              <div className={tenantAdminEnabled ? "grid gap-2 md:grid-cols-3" : "grid gap-2"}>
                {tenantAdminEnabled ? (
                  <>
                    <Input
                      value={groupChainIds}
                      onChange={(event) => setGroupChainIds(event.target.value)}
                      placeholder="IDs cadena: 1,2"
                    />
                    <Input
                      value={groupHotelIds}
                      onChange={(event) => setGroupHotelIds(event.target.value)}
                      placeholder="IDs hotel: 3,4"
                    />
                  </>
                ) : null}
                <Input
                  value={groupDeniedTags}
                  onChange={(event) => setGroupDeniedTags(event.target.value)}
                  placeholder="tags bloqueados"
                />
              </div>
              <div className="flex flex-wrap gap-3 text-sm">
                {tenantAdminEnabled ? (
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={groupAllowAll}
                      onChange={(event) => setGroupAllowAll(event.target.checked)}
                    />
                    Todos los hoteles
                  </label>
                ) : null}
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={groupCanPrices}
                    onChange={(event) => setGroupCanPrices(event.target.checked)}
                  />
                  Ver precios
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={groupCanSearchBudgets}
                    onChange={(event) => setGroupCanSearchBudgets(event.target.checked)}
                  />
                  Buscar presupuestos
                </label>
              </div>
              <Button disabled={createAccessGroup.isPending}>Crear grupo</Button>
            </form>
            <SimpleTable
              headings={["Grupo", "Permisos", "Tags bloqueados"]}
              rows={accessGroups.map((group) => [
                group.name,
                [
                  group.permissions_json.can_view_prices ? "precios" : "sin precios",
                  group.permissions_json.can_search_budgets
                    ? "busca presupuestos"
                    : "busqueda limitada",
                  tenantAdminEnabled
                    ? group.permissions_json.allow_all_hotels
                      ? "todos hoteles"
                      : `hoteles: ${String(group.permissions_json.hotel_ids ?? "[]")}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" &middot; "),
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
              onSubmit={(event: FormEvent) => {
                event.preventDefault()
                if (memberGroupId && memberPrincipalId.trim()) upsertMember.mutate()
              }}
            >
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={memberGroupId}
                onChange={(event) => setMemberGroupId(event.target.value)}
              >
                <option value="">Grupo</option>
                {accessGroups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.name}
                  </option>
                ))}
              </select>
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={memberType}
                onChange={(event) => setMemberType(event.target.value as "user" | "technician")}
              >
                <option value="technician">T&eacute;cnico externo</option>
                <option value="user">Usuario interno</option>
              </select>
              <Input
                value={memberPrincipalId}
                onChange={(event) => setMemberPrincipalId(event.target.value)}
                placeholder="ID t&eacute;cnico o ID usuario"
              />
              <Button disabled={upsertMember.isPending}>Asignar</Button>
            </form>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Tags sensibles</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <form
            className="grid gap-2 md:grid-cols-[220px_1fr_auto]"
            onSubmit={(event: FormEvent) => {
              event.preventDefault()
              if (tagName.trim()) createSensitiveTag.mutate()
            }}
          >
            <Input
              value={tagName}
              onChange={(event) => setTagName(event.target.value)}
              placeholder="contabilidad"
            />
            <Input
              value={tagDescription}
              onChange={(event) => setTagDescription(event.target.value)}
              placeholder="Descripci&oacute;n"
            />
            <Button disabled={createSensitiveTag.isPending}>Crear tag</Button>
          </form>
          <SimpleTable
            headings={["Tag", "Descripci&oacute;n", "Estado"]}
            rows={sensitiveTags.map((tag) => [
              tag.name,
              tag.description ?? "-",
              tag.is_active ? "Activo" : "Inactivo",
            ])}
          />
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Simulador de acceso</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <form
              className="grid gap-2"
              onSubmit={(event: FormEvent) => {
                event.preventDefault()
                if (explainPrincipalId.trim() && Number(explainDocumentId) > 0)
                  explainAccess.mutate()
              }}
            >
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={explainPrincipalType}
                onChange={(event) =>
                  setExplainPrincipalType(event.target.value as "user" | "technician")
                }
              >
                <option value="technician">T&eacute;cnico externo</option>
                <option value="user">Usuario interno</option>
              </select>
              <div className="grid gap-2 md:grid-cols-[1fr_120px_auto]">
                <Input
                  value={explainPrincipalId}
                  onChange={(event) => setExplainPrincipalId(event.target.value)}
                  placeholder="ID principal"
                />
                <Input
                  value={explainDocumentId}
                  onChange={(event) => setExplainDocumentId(event.target.value)}
                  placeholder="Doc ID"
                />
                <Button disabled={explainAccess.isPending}>Comprobar</Button>
              </div>
            </form>
            {explainAccess.data ? (
              <div className="rounded-md border p-3 text-sm">
                <Badge variant={explainAccess.data.allowed ? "success" : "destructive"}>
                  {explainAccess.data.allowed ? "Permitido" : "Denegado"}
                </Badge>
                <ul className="mt-2 space-y-1 text-muted-foreground">
                  {explainAccess.data.reasons.map((reason: string) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {explainAccess.isError ? (
              <p className="text-sm text-destructive">{explainAccess.error?.message}</p>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Preview reglas</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <form
              className="grid gap-2"
              onSubmit={(event: FormEvent) => {
                event.preventDefault()
                if (rulePreviewPath.trim() && rulePreviewPattern.trim()) previewRule.mutate()
              }}
            >
              <Input
                value={rulePreviewPath}
                onChange={(event) => setRulePreviewPath(event.target.value)}
                placeholder="Ruta de archivo"
              />
              <Input
                value={rulePreviewPattern}
                onChange={(event) => setRulePreviewPattern(event.target.value)}
                placeholder="/presupuestos/"
              />
              <Input
                value={rulePreviewTags}
                onChange={(event) => setRulePreviewTags(event.target.value)}
                placeholder="tags separados por coma"
              />
              <Button disabled={previewRule.isPending}>Probar regla</Button>
            </form>
            {previewRule.data ? (
              <div className="rounded-md border p-2">
                <Badge variant={previewRule.data.matches ? "success" : "warning"}>
                  {previewRule.data.matches ? "Coincide" : "No coincide"}
                </Badge>
                <p className="mt-2 text-xs text-muted-foreground">
                  {previewRule.data.normalized_path}
                </p>
              </div>
            ) : null}
            {previewRule.isError ? (
              <p className="text-sm text-destructive">{previewRule.error?.message}</p>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Preview redacci&oacute;n</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <form
              className="grid gap-2"
              onSubmit={(event: FormEvent) => {
                event.preventDefault()
                if (redactionPrincipalId.trim() && redactionText.trim()) previewRedaction.mutate()
              }}
            >
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={redactionPrincipalType}
                onChange={(event) =>
                  setRedactionPrincipalType(event.target.value as "user" | "technician")
                }
              >
                <option value="technician">T&eacute;cnico</option>
                <option value="user">Usuario</option>
              </select>
              <Input
                value={redactionPrincipalId}
                onChange={(event) => setRedactionPrincipalId(event.target.value)}
                placeholder="ID principal"
              />
              <Input
                value={redactionText}
                onChange={(event) => setRedactionText(event.target.value)}
                placeholder="Texto con importes"
              />
              <Button disabled={previewRedaction.isPending}>Ver redacci&oacute;n</Button>
            </form>
            {previewRedaction.data ? (
              <div className="rounded-md border p-2">
                <Badge variant={previewRedaction.data.can_view_prices ? "warning" : "success"}>
                  {previewRedaction.data.can_view_prices ? "Ve precios" : "Precios ocultos"}
                </Badge>
                <p className="mt-2 text-xs leading-5">{previewRedaction.data.redacted_text}</p>
              </div>
            ) : null}
            {previewRedaction.isError ? (
              <p className="text-sm text-destructive">{previewRedaction.error?.message}</p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
