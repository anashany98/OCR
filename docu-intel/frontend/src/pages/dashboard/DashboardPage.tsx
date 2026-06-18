import {
  AlertsCard,
  DashboardHero,
  DistributionCard,
  InfrastructureCard,
  MetricStrip,
  OnboardingCallout,
  PriorityWorkCard,
  ShortcutsCard,
  UrgentActionsSection,
} from "./components"
import { useDashboard } from "./useDashboard"

// ---------------------------------------------------------------------------
// F8b-cont4 - dashboard page composition
//
// The previous file was 23 KB / 505 lines mixing six queries,
// state for onboarding, an UrgentAction registry, the editorial
// hero with animated count-up, the metric strip, two card-based
// left-column sections (priority work, distribution), three
// right-column cards (infrastructure, alerts, shortcuts) and
// inline sub-components (UrgentActionCard, PriorityWorkCard,
// DistributionCard, DistributionColumn, InfrastructureCard,
// InfraRow, AlertsCard).
//
// After F8b-cont4:
// - useDashboard() owns every piece of state and the six
//   queries. Returns the raw data + derived flags.
// - Pure helpers extracted and exported: getCheckStatus,
//   getDiskStatus, formatDiskSpace, buildUrgentActions.
//   10 unit tests cover each one.
// - Components.tsx provides every sub-component as a small
//   testable piece.
// - The page itself is a thin layout shell.
// ---------------------------------------------------------------------------
export function DashboardPage() {
  const d = useDashboard()
  const criticalInboxCount = d.inboxItems.filter(
    (i) => i.severity === "error" || i.severity === "critical",
  ).length
  return (
    <div className="space-y-8">
      {d.isFirstTime && <OnboardingCallout />}
      <DashboardHero stats={d.d} isLoading={d.isLoading} />
      <UrgentActionsSection actions={d.urgentActions} />
      <MetricStrip
        stats={d.d}
        isLoading={d.isLoading}
        ov={d.ov}
        inboxCount={d.inboxItems.length}
        criticalInboxCount={criticalInboxCount}
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-6">
          <PriorityWorkCard inboxItems={d.inboxItems} />
          <DistributionCard metrics={d.metrics.data} />
        </div>
        <div className="space-y-6">
          <InfrastructureCard sh={d.sh} ov={d.ov} />
          <AlertsCard alertItems={d.alertItems} />
          <ShortcutsCard />
        </div>
      </div>
    </div>
  )
}
