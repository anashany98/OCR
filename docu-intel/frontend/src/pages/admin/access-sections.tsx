import { type FormEvent } from "react"
import { RefreshCw } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { StyledSelect } from "@/components/ui/styled-select"
import { SimpleTable } from "./shared"
import type {
  AccessGroupsSectionProps,
  AccessSimulatorSectionProps,
  ChainsSectionProps,
  FolderRulesSectionProps,
  HotelsSectionProps,
  MembersSectionProps,
  RedactionPreviewSectionProps,
  RulePreviewSectionProps,
  SensitiveTagsSectionProps,
} from "./access-types"

// ---------------------------------------------------------------------------
// Chains + Hotels (tenant-only)
// ---------------------------------------------------------------------------

export function ChainsHotelsSection({
  chains,
  chainName,
  setChainName,
  createChain,
  hotels,
  hotelName,
  setHotelName,
  hotelCode,
  setHotelCode,
  hotelChainId,
  setHotelChainId,
  createHotel,
}: ChainsSectionProps & HotelsSectionProps) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Cadenas</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <form
            className="flex gap-2"
            onSubmit={(e: FormEvent) => {
              e.preventDefault()
              if (chainName.trim()) createChain.mutate()
            }}
          >
            <Input
              value={chainName}
              onChange={(e) => setChainName(e.target.value)}
              placeholder="Nombre de cadena"
            />
            <Button disabled={createChain.isPending}>Crear</Button>
          </form>
          <SimpleTable
            rows={chains.map((c) => [c.name, c.is_active ? "Activa" : "Inactiva"])}
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
            onSubmit={(e: FormEvent) => {
              e.preventDefault()
              if (hotelName.trim() && hotelChainId) createHotel.mutate()
            }}
          >
            <StyledSelect value={hotelChainId} onChange={(e) => setHotelChainId(e.target.value)}>
              <option value="">Cadena</option>
              {chains.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </StyledSelect>
            <Input
              value={hotelName}
              onChange={(e) => setHotelName(e.target.value)}
              placeholder="Hotel"
            />
            <Input
              value={hotelCode}
              onChange={(e) => setHotelCode(e.target.value)}
              placeholder="Código"
            />
            <Button disabled={createHotel.isPending}>Crear</Button>
          </form>
          <SimpleTable
            headings={["Hotel", "Cadena", "Código"]}
            rows={hotels.map((h) => [
              h.name,
              chains.find((c) => c.id === h.chain_id)?.name ?? String(h.chain_id),
              h.code ?? "-",
            ])}
          />
        </CardContent>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Folder Rules (tenant-only)
// ---------------------------------------------------------------------------

export function FolderRulesSection({
  chains,
  hotels,
  folderRules,
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
}: FolderRulesSectionProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Reglas de carpetas</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <form
          className="grid gap-2 lg:grid-cols-[1fr_1.4fr_180px_180px_1fr_auto]"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (rulePattern.trim()) createFolderRule.mutate()
          }}
        >
          <Input
            value={ruleName}
            onChange={(e) => setRuleName(e.target.value)}
            placeholder="Nombre"
          />
          <Input
            value={rulePattern}
            onChange={(e) => setRulePattern(e.target.value)}
            placeholder="/presupuestos/cadena/hotel/"
          />
          <StyledSelect value={ruleChainId} onChange={(e) => setRuleChainId(e.target.value)}>
            <option value="">Cadena</option>
            {chains.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </StyledSelect>
          <StyledSelect value={ruleHotelId} onChange={(e) => setRuleHotelId(e.target.value)}>
            <option value="">Hotel</option>
            {hotels.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </StyledSelect>
          <Input
            value={ruleTags}
            onChange={(e) => setRuleTags(e.target.value)}
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
          <RefreshCw data-icon="inline-start" /> Reaplicar reglas
        </Button>
        {applyFolderRules.data && (
          <p className="text-sm text-[var(--text-muted)]">
            Asignados: {applyFolderRules.data.assigned}. Cuarentena:{" "}
            {applyFolderRules.data.quarantined}. Omitidos: {applyFolderRules.data.skipped}.
          </p>
        )}
        <SimpleTable
          headings={["Patrón", "Cadena", "Hotel", "Tags", "Estado"]}
          rows={folderRules.map((r) => [
            r.pattern,
            chains.find((c) => c.id === r.chain_id)?.name ?? "-",
            hotels.find((h) => h.id === r.hotel_id)?.name ?? "-",
            r.tags_json.join(", ") || "-",
            r.is_active ? "Activa" : "Inactiva",
          ])}
        />
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Access Groups
// ---------------------------------------------------------------------------

export function AccessGroupsSection({
  accessGroups,
  tenantAdminEnabled,
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
}: AccessGroupsSectionProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Perfiles y grupos</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <form
          className="grid gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (groupName.trim()) createAccessGroup.mutate()
          }}
        >
          <Input
            value={groupName}
            onChange={(e) => setGroupName(e.target.value)}
            placeholder="Nombre del grupo"
          />
          <div className={tenantAdminEnabled ? "grid gap-2 md:grid-cols-3" : "grid gap-2"}>
            {tenantAdminEnabled && (
              <>
                <Input
                  value={groupChainIds}
                  onChange={(e) => setGroupChainIds(e.target.value)}
                  placeholder="IDs cadena: 1,2"
                />
                <Input
                  value={groupHotelIds}
                  onChange={(e) => setGroupHotelIds(e.target.value)}
                  placeholder="IDs hotel: 3,4"
                />
              </>
            )}
            <Input
              value={groupDeniedTags}
              onChange={(e) => setGroupDeniedTags(e.target.value)}
              placeholder="tags bloqueados"
            />
          </div>
          <div className="flex flex-wrap gap-3 text-sm">
            {tenantAdminEnabled && (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={groupAllowAll}
                  onChange={(e) => setGroupAllowAll(e.target.checked)}
                />
                Todos los hoteles
              </label>
            )}
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={groupCanPrices}
                onChange={(e) => setGroupCanPrices(e.target.checked)}
              />
              Ver precios
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={groupCanSearchBudgets}
                onChange={(e) => setGroupCanSearchBudgets(e.target.checked)}
              />
              Buscar presupuestos
            </label>
          </div>
          <Button disabled={createAccessGroup.isPending}>Crear grupo</Button>
        </form>
        <SimpleTable
          headings={["Grupo", "Permisos", "Tags bloqueados"]}
          rows={accessGroups.map((g) => [
            g.name,
            [
              g.permissions_json.can_view_prices ? "precios" : "sin precios",
              g.permissions_json.can_search_budgets ? "busca presupuestos" : "búsqueda limitada",
              tenantAdminEnabled
                ? g.permissions_json.allow_all_hotels
                  ? "todos hoteles"
                  : `hoteles: ${String(g.permissions_json.hotel_ids ?? "[]")}`
                : null,
            ]
              .filter(Boolean)
              .join(" · "),
            String(g.permissions_json.denied_tags ?? "[]"),
          ])}
        />
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Members
// ---------------------------------------------------------------------------

export function MembersSection({
  accessGroups,
  memberGroupId,
  setMemberGroupId,
  memberType,
  setMemberType,
  memberPrincipalId,
  setMemberPrincipalId,
  upsertMember,
}: MembersSectionProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Asignar miembros</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <form
          className="grid gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (memberGroupId && memberPrincipalId.trim()) upsertMember.mutate()
          }}
        >
          <StyledSelect value={memberGroupId} onChange={(e) => setMemberGroupId(e.target.value)}>
            <option value="">Grupo</option>
            {accessGroups.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </StyledSelect>
          <StyledSelect
            value={memberType}
            onChange={(e) => setMemberType(e.target.value as "user" | "technician")}
          >
            <option value="technician">Técnico externo</option>
            <option value="user">Usuario interno</option>
          </StyledSelect>
          <Input
            value={memberPrincipalId}
            onChange={(e) => setMemberPrincipalId(e.target.value)}
            placeholder="ID técnico o ID usuario"
          />
          <Button disabled={upsertMember.isPending}>Asignar</Button>
        </form>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Sensitive Tags
// ---------------------------------------------------------------------------

export function SensitiveTagsSection({
  sensitiveTags,
  tagName,
  setTagName,
  tagDescription,
  setTagDescription,
  createSensitiveTag,
}: SensitiveTagsSectionProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Tags sensibles</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <form
          className="grid gap-2 md:grid-cols-[220px_1fr_auto]"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (tagName.trim()) createSensitiveTag.mutate()
          }}
        >
          <Input
            value={tagName}
            onChange={(e) => setTagName(e.target.value)}
            placeholder="contabilidad"
          />
          <Input
            value={tagDescription}
            onChange={(e) => setTagDescription(e.target.value)}
            placeholder="Descripción"
          />
          <Button disabled={createSensitiveTag.isPending}>Crear tag</Button>
        </form>
        <SimpleTable
          headings={["Tag", "Descripción", "Estado"]}
          rows={sensitiveTags.map((t) => [
            t.name,
            t.description ?? "-",
            t.is_active ? "Activo" : "Inactivo",
          ])}
        />
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Access Simulator
// ---------------------------------------------------------------------------

export function AccessSimulatorSection({
  explainPrincipalType,
  setExplainPrincipalType,
  explainPrincipalId,
  setExplainPrincipalId,
  explainDocumentId,
  setExplainDocumentId,
  explainAccess,
}: AccessSimulatorSectionProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Simulador de acceso</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <form
          className="grid gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (explainPrincipalId.trim() && Number(explainDocumentId) > 0) explainAccess.mutate()
          }}
        >
          <StyledSelect
            value={explainPrincipalType}
            onChange={(e) => setExplainPrincipalType(e.target.value as "user" | "technician")}
          >
            <option value="technician">Técnico externo</option>
            <option value="user">Usuario interno</option>
          </StyledSelect>
          <div className="grid gap-2 md:grid-cols-[1fr_120px_auto]">
            <Input
              value={explainPrincipalId}
              onChange={(e) => setExplainPrincipalId(e.target.value)}
              placeholder="ID principal"
            />
            <Input
              value={explainDocumentId}
              onChange={(e) => setExplainDocumentId(e.target.value)}
              placeholder="Doc ID"
            />
            <Button disabled={explainAccess.isPending}>Comprobar</Button>
          </div>
        </form>
        {explainAccess.data && (
          <div className="rounded-md border p-3 text-sm">
            <Badge variant={explainAccess.data.allowed ? "success" : "destructive"}>
              {explainAccess.data.allowed ? "Permitido" : "Denegado"}
            </Badge>
            <ul className="mt-2 space-y-1 text-[var(--text-muted)]">
              {explainAccess.data.reasons.map((reason: string) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        )}
        {explainAccess.isError && (
          <p className="text-sm text-[var(--danger)]">{explainAccess.error?.message}</p>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Rule Preview
// ---------------------------------------------------------------------------

export function RulePreviewSection({
  rulePreviewPath,
  setRulePreviewPath,
  rulePreviewPattern,
  setRulePreviewPattern,
  rulePreviewTags,
  setRulePreviewTags,
  previewRule,
}: RulePreviewSectionProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Preview reglas</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <form
          className="grid gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (rulePreviewPath.trim() && rulePreviewPattern.trim()) previewRule.mutate()
          }}
        >
          <Input
            value={rulePreviewPath}
            onChange={(e) => setRulePreviewPath(e.target.value)}
            placeholder="Ruta de archivo"
          />
          <Input
            value={rulePreviewPattern}
            onChange={(e) => setRulePreviewPattern(e.target.value)}
            placeholder="/presupuestos/"
          />
          <Input
            value={rulePreviewTags}
            onChange={(e) => setRulePreviewTags(e.target.value)}
            placeholder="tags separados por coma"
          />
          <Button disabled={previewRule.isPending}>Probar regla</Button>
        </form>
        {previewRule.data && (
          <div className="rounded-md border p-2">
            <Badge variant={previewRule.data.matches ? "success" : "warning"}>
              {previewRule.data.matches ? "Coincide" : "No coincide"}
            </Badge>
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              {previewRule.data.normalized_path}
            </p>
          </div>
        )}
        {previewRule.isError && (
          <p className="text-sm text-[var(--danger)]">{previewRule.error?.message}</p>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Redaction Preview
// ---------------------------------------------------------------------------

export function RedactionPreviewSection({
  redactionPrincipalType,
  setRedactionPrincipalType,
  redactionPrincipalId,
  setRedactionPrincipalId,
  redactionText,
  setRedactionText,
  previewRedaction,
}: RedactionPreviewSectionProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Preview redacción</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <form
          className="grid gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault()
            if (redactionPrincipalId.trim() && redactionText.trim()) previewRedaction.mutate()
          }}
        >
          <StyledSelect
            value={redactionPrincipalType}
            onChange={(e) => setRedactionPrincipalType(e.target.value as "user" | "technician")}
          >
            <option value="technician">Técnico</option>
            <option value="user">Usuario</option>
          </StyledSelect>
          <Input
            value={redactionPrincipalId}
            onChange={(e) => setRedactionPrincipalId(e.target.value)}
            placeholder="ID principal"
          />
          <Input
            value={redactionText}
            onChange={(e) => setRedactionText(e.target.value)}
            placeholder="Texto con importes"
          />
          <Button disabled={previewRedaction.isPending}>Ver redacción</Button>
        </form>
        {previewRedaction.data && (
          <div className="rounded-md border p-2">
            <Badge variant={previewRedaction.data.can_view_prices ? "warning" : "success"}>
              {previewRedaction.data.can_view_prices ? "Ve precios" : "Precios ocultos"}
            </Badge>
            <p className="mt-2 text-xs leading-5">{previewRedaction.data.redacted_text}</p>
          </div>
        )}
        {previewRedaction.isError && (
          <p className="text-sm text-[var(--danger)]">{previewRedaction.error?.message}</p>
        )}
      </CardContent>
    </Card>
  )
}
