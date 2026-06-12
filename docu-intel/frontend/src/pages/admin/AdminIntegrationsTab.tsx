import type { FormEvent } from "react"
import { KeyRound } from "lucide-react"

import type { IntegrationClient, IntegrationToolResponse } from "@/types/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { parseJsonObject } from "./shared"

interface MutationLike<TData = unknown> {
  mutate: () => void
  isPending: boolean
  data?: TData
  isError: boolean
  error: Error | null
}

interface RotateKeyMutation {
  mutate: (clientId: number) => void
  isPending: boolean
}

interface AdminIntegrationsTabProps {
  integrationClients: IntegrationClient[]
  apiClientName: string
  setApiClientName: (v: string) => void
  apiClientScopes: string
  setApiClientScopes: (v: string) => void
  createIntegrationClient: MutationLike<IntegrationClient>
  rotateIntegrationClientKey: RotateKeyMutation
  latestApiKey: string | null
  setLatestApiKey: (v: string | null) => void
  sandboxClientId: string
  setSandboxClientId: (v: string) => void
  sandboxTechnicianId: string
  setSandboxTechnicianId: (v: string) => void
  sandboxTool: string
  setSandboxTool: (v: string) => void
  sandboxArguments: string
  setSandboxArguments: (v: string) => void
  runIntegrationSandbox: MutationLike<IntegrationToolResponse>
  roundTrip: number
  setRoundTrip: (v: number) => void
}

export function AdminIntegrationsTab({
  integrationClients,
  apiClientName,
  setApiClientName,
  apiClientScopes,
  setApiClientScopes,
  createIntegrationClient,
  rotateIntegrationClientKey,
  latestApiKey,
  setLatestApiKey,
  sandboxClientId,
  setSandboxClientId,
  sandboxTechnicianId,
  setSandboxTechnicianId,
  sandboxTool,
  setSandboxTool,
  sandboxArguments,
  setSandboxArguments,
  runIntegrationSandbox,
  roundTrip,
  setRoundTrip,
}: AdminIntegrationsTabProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Clientes API para IA externa</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          className="grid gap-2 md:grid-cols-[1fr_220px_auto]"
          onSubmit={(event: FormEvent) => {
            event.preventDefault()
            if (apiClientName.trim()) createIntegrationClient.mutate()
          }}
        >
          <Input
            value={apiClientName}
            onChange={(event) => setApiClientName(event.target.value)}
            placeholder="Nombre del cliente"
          />
          <Input
            value={apiClientScopes}
            onChange={(event) => setApiClientScopes(event.target.value)}
            placeholder="read,upload,admin"
          />
          <Button disabled={createIntegrationClient.isPending}>
            <KeyRound data-icon="inline-start" />
            Crear
          </Button>
        </form>
        {latestApiKey ? (
          <div className="rounded-md border border-warning/50 bg-warning/10 p-3 text-sm">
            <p className="font-medium">API key generada. Se muestra solo una vez.</p>
            <code className="mt-2 block break-all rounded bg-background px-2 py-1">
              {latestApiKey}
            </code>
          </div>
        ) : null}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Cliente</TableHead>
              <TableHead>Scopes</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>&Uacute;ltimo uso</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {integrationClients.map((client) => (
              <TableRow key={client.id}>
                <TableCell>{client.name}</TableCell>
                <TableCell>{client.scopes_json.join(", ")}</TableCell>
                <TableCell>
                  <Badge variant={client.is_active ? "success" : "secondary"}>
                    {client.is_active ? "Activo" : "Inactivo"}
                  </Badge>
                </TableCell>
                <TableCell>
                  {client.last_used_at ? new Date(client.last_used_at).toLocaleString() : "-"}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      if (window.confirm('¿Rotar la API key del cliente "' + client.name + '"?'))
                        rotateIntegrationClientKey.mutate(client.id)
                    }}
                  >
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
            <p className="text-xs text-muted-foreground">
              Ejecuta una tool como la ver&iacute;a la IA externa, con redacciones y fuentes.
            </p>
          </div>
          <form
            className="grid gap-2 lg:grid-cols-[140px_180px_220px_1fr_auto]"
            onSubmit={(event: FormEvent) => {
              event.preventDefault()
              if (Number(sandboxClientId) > 0 && sandboxTechnicianId.trim() && sandboxTool.trim())
                runIntegrationSandbox.mutate()
            }}
          >
            <select
              className="h-9 rounded-md border bg-background px-3 text-sm"
              value={sandboxClientId}
              onChange={(event) => setSandboxClientId(event.target.value)}
            >
              <option value="">Cliente</option>
              {integrationClients.map((client) => (
                <option key={client.id} value={client.id}>
                  {client.name}
                </option>
              ))}
            </select>
            <Input
              value={sandboxTechnicianId}
              onChange={(event) => setSandboxTechnicianId(event.target.value)}
              placeholder="T&eacute;cnico"
            />
            <Input
              value={sandboxTool}
              onChange={(event) => setSandboxTool(event.target.value)}
              placeholder="Tool"
            />
            <Input
              value={sandboxArguments}
              onChange={(event) => setSandboxArguments(event.target.value)}
              placeholder='{"budget_number":"2026/143"}'
            />
            <Button disabled={runIntegrationSandbox.isPending}>Probar</Button>
          </form>
          <div className="flex items-center gap-3 mt-3">
            <label className="text-sm text-muted-foreground flex items-center gap-2">
              Round-trip (ms):
              <Input
                type="number"
                value={roundTrip}
                onChange={(e) => setRoundTrip(Number(e.target.value))}
                className="w-24 h-8 text-sm"
                min={0}
              />
            </label>
          </div>
          {runIntegrationSandbox.data ? (
            <pre className="mt-3 max-h-72 overflow-auto rounded-md bg-muted p-3 text-xs">
              {JSON.stringify(runIntegrationSandbox.data, null, 2)}
            </pre>
          ) : null}
          {runIntegrationSandbox.isError ? (
            <p className="mt-2 text-sm text-destructive">{runIntegrationSandbox.error?.message}</p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}
