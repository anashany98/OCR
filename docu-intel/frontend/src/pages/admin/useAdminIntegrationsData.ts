/**
 * useAdminIntegrationsData - queries and state for the
 * ``/admin/integraciones`` tab (API clients, sandbox tester).
 */
import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"

import { csv } from "./shared"

export function useAdminIntegrationsData() {
  const queryClient = useQueryClient()

  const [apiClientName, setApiClientName] = useState("")
  const [apiClientScopes, setApiClientScopes] = useState("read,upload")
  const [latestApiKey, setLatestApiKey] = useState<string | null>(null)
  const [sandboxClientId, setSandboxClientId] = useState("")
  const [sandboxTechnicianId, setSandboxTechnicianId] = useState("tecnico-demo")
  const [sandboxTool, setSandboxTool] = useState("get_budget_by_number")
  const [sandboxArguments, setSandboxArguments] = useState('{"budget_number":"2026/143"}')
  const [roundTrip, setRoundTrip] = useState(0)

  const integrationClients = useQuery({
    queryKey: ["integration-clients"],
    queryFn: api.integrationClients,
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
      void queryClient.invalidateQueries({ queryKey: ["integration-clients"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })
  const rotateIntegrationClientKey = useMutation({
    mutationFn: (clientId: number) => api.rotateIntegrationClientKey(clientId),
    onSuccess: (client) => {
      setLatestApiKey(client.api_key ?? null)
      void queryClient.invalidateQueries({ queryKey: ["integration-clients"] })
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
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
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
    },
  })

  return {
    state: {
      apiClientName,
      setApiClientName,
      apiClientScopes,
      setApiClientScopes,
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
      roundTrip,
      setRoundTrip,
    },
    queries: { integrationClients },
    mutations: { createIntegrationClient, rotateIntegrationClientKey, runIntegrationSandbox },
  }
}

export type AdminIntegrationsData = ReturnType<typeof useAdminIntegrationsData>
