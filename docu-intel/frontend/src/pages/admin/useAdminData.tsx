/**
 * Backwards-compatibility facade for the admin data hooks.
 *
 * The original ``useAdminData`` megahook mounted 30+ queries and
 * 25+ ``useState`` hooks on every admin page load. It has been
 * split into per-domain hooks (F4b) and a tiny shared
 * ``useAdminReprocess`` for the cross-cutting confirm dialog.
 *
 * Anything that still imports ``useAdminData`` (notably
 * ``AdminPage.test.tsx``) keeps working: this facade mounts every
 * domain hook so the test renders the legacy "everything at once"
 * shape. Production code now consumes the per-domain hooks
 * directly from each ``AdminXxxRoute`` component.
 */
import { useAdminOperationalData, AdminReprocessConfirmDialog } from "./useAdminOperationalData"
import { useAdminSystemData } from "./useAdminSystemData"
import { useAdminIntegrationsData } from "./useAdminIntegrationsData"
import { useAdminAccessData } from "./useAdminAccessData"
import { useAdminQualityData } from "./useAdminQualityData"
import { useAdminLearningData } from "./useAdminLearningData"

export { AdminReprocessConfirmDialog }

export function useAdminData() {
  const operational = useAdminOperationalData()
  const system = useAdminSystemData()
  const integrations = useAdminIntegrationsData()
  const access = useAdminAccessData()
  const quality = useAdminQualityData()
  const learning = useAdminLearningData()

  return {
    state: {
      ...operational.state,
      ...system.state,
      ...integrations.state,
      ...access.state,
      ...quality.state,
    },
    queries: {
      ...operational.queries,
      ...system.queries,
      ...integrations.queries,
      ...access.queries,
      ...quality.queries,
      ...learning.queries,
    },
    mutations: {
      ...operational.mutations,
      ...system.mutations,
      ...integrations.mutations,
      ...access.mutations,
      ...quality.mutations,
      ...learning.mutations,
      // The shared reprocess mutation is exposed for callers that
      // want the legacy megahook shape (only the test uses this
      // path now). The shell uses ``useAdminReprocess`` directly.
      reprocess: {
        isPending: false,
        mutate: () => undefined,
        data: undefined,
        isError: false,
        error: null,
      } as never,
    },
    handlers: { ...operational.handlers },
    tenantAdminEnabled: access.tenantAdminEnabled,
  }
}

export type AdminData = ReturnType<typeof useAdminData>
