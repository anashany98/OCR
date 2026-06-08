import { useOutletContext } from "react-router-dom"

import { AdminIntegrationsTab } from "./AdminIntegrationsTab"
import type { AdminData } from "./useAdminData"

export function AdminIntegrationsRoute() {
  const data = useOutletContext<AdminData>()
  const { state, queries, mutations } = data

  return (
    <AdminIntegrationsTab
      integrationClients={queries.integrationClients.data ?? []}
      apiClientName={state.apiClientName}
      setApiClientName={state.setApiClientName}
      apiClientScopes={state.apiClientScopes}
      setApiClientScopes={state.setApiClientScopes}
      createIntegrationClient={{
        mutate: () => mutations.createIntegrationClient.mutate(),
        isPending: mutations.createIntegrationClient.isPending,
        data: mutations.createIntegrationClient.data,
        isError: mutations.createIntegrationClient.isError,
        error: mutations.createIntegrationClient.error,
      }}
      rotateIntegrationClientKey={{
        mutate: mutations.rotateIntegrationClientKey.mutate,
        isPending: mutations.rotateIntegrationClientKey.isPending,
      }}
      latestApiKey={state.latestApiKey}
      setLatestApiKey={state.setLatestApiKey}
      sandboxClientId={state.sandboxClientId}
      setSandboxClientId={state.setSandboxClientId}
      sandboxTechnicianId={state.sandboxTechnicianId}
      setSandboxTechnicianId={state.setSandboxTechnicianId}
      sandboxTool={state.sandboxTool}
      setSandboxTool={state.setSandboxTool}
      sandboxArguments={state.sandboxArguments}
      setSandboxArguments={state.setSandboxArguments}
      runIntegrationSandbox={{
        mutate: () => mutations.runIntegrationSandbox.mutate(),
        isPending: mutations.runIntegrationSandbox.isPending,
        data: mutations.runIntegrationSandbox.data,
        isError: mutations.runIntegrationSandbox.isError,
        error: mutations.runIntegrationSandbox.error,
      }}
      roundTrip={state.roundTrip}
      setRoundTrip={state.setRoundTrip}
    />
  )
}
