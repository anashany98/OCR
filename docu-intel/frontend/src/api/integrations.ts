import type { IntegrationClient, IntegrationToolResponse } from "@/types/api"
import { request } from "./core"

export const integrationsApi = {
  integrationClients: () => request<IntegrationClient[]>("/admin/integration-clients"),
  createIntegrationClient: (payload: { name: string; scopes: string[]; is_active?: boolean }) =>
    request<IntegrationClient>("/admin/integration-clients", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateIntegrationClient: (
    id: number,
    payload: { name?: string; scopes?: string[]; is_active?: boolean },
  ) =>
    request<IntegrationClient>("/admin/integration-clients/" + id, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  rotateIntegrationClientKey: (id: number) =>
    request<IntegrationClient>("/admin/integration-clients/" + id + "/rotate-key", {
      method: "POST",
    }),
  integrationSandbox: (payload: {
    client_id: number
    technician_id: string
    technician_name?: string | null
    tool: string
    arguments: Record<string, unknown>
  }) =>
    request<IntegrationToolResponse>("/admin/integration-sandbox/execute", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
}
