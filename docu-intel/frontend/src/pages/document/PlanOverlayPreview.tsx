/**
 * PM7 + S5.1 — Lightweight plan overlay preview for DocumentDetailPage.
 *
 * The dedicated PlanoAnnotationPage already provides the full editing
 * experience (SVG canvas, dimension capture, polygon building, scale
 * calibration). This component is a *read-only preview* meant to live
 * on the generic document detail page so a user opening a `plano`
 * document sees, at a glance, which annotations the system has
 * detected and can choose to jump to the full editor with a single
 * click.
 *
 * The component is intentionally simple: it shows the count and a
 * short label per overlay kind (cajetin / legend / chat facts /
 * revisions) and renders nothing while the query is loading. The
 * heavy lifting (rendering SVG bboxes over the page image) is left
 * to the dedicated editor — the detail page only needs the *existence*
 * of the overlays to be discoverable.
 *
 * Plan resolution: the caller passes only ``documentId``. The component
 * resolves the associated ``plan_id`` itself via ``usePlanForDocument``
 * (which lists plans and filters by ``document_id``, the same pattern
 * used by ``usePlanAnnotation``). A ``planId`` prop is accepted only as
 * an escape hatch for callers/tests that already hold the resolved id.
 */
import { usePlanForDocument } from "@/pages/plano/usePlanForDocument"
import { usePlanOverlays } from "@/pages/plano/usePlanOverlays"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Link } from "react-router-dom"
import { MapPin } from "lucide-react"

type Props = {
  documentId: number
  /**
   * Optional pre-resolved plan id. When omitted (the normal case from
   * ``DocumentDetailPage``) the component resolves it from
   * ``documentId`` via ``usePlanForDocument``.
   */
  planId?: number | null
}

const KIND_LABELS: Record<string, string> = {
  cajetin: "Cajetin",
  legend: "Leyenda",
  chat_facts: "Datos del chat",
  revision: "Revisiones",
}

export function PlanOverlayPreview({ documentId, planId }: Props) {
  // Resolve the plan id from the document when the caller did not
  // supply one. We always call the hook (rules of hooks): if
  // ``planId`` is provided, the hook result is simply ignored.
  const resolved = usePlanForDocument(planId == null ? documentId : null)
  const effectivePlanId = planId ?? resolved.planId

  const overlays = usePlanOverlays(effectivePlanId, documentId)

  // Derive a coarse summary from the per-kind arrays. The counts
  // are an approximation: a cajetin / legend is identified by
  // `region_type` starting with the kind name (the API uses
  // "cajetin_xxx" and "legend_xxx" labels). Anything else falls
  // under "chat facts" or "revisions" via the dedicated arrays.
  const summary = {
    cajetin: overlays.overlays.filter((o) =>
      o.region_type.toLowerCase().startsWith("cajetin"),
    ).length,
    legend: overlays.overlays.filter((o) =>
      o.region_type.toLowerCase().startsWith("legend"),
    ).length,
    chatFacts: overlays.chatFacts.length,
    revisions: overlays.revisions.length,
  }
  const total =
    summary.cajetin + summary.legend + summary.chatFacts + summary.revisions

  return (
    <Card data-testid="plan-overlay-preview">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <MapPin className="h-4 w-4" /> Anotaciones de plano
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        {total === 0 ? (
          <p className="text-muted-foreground">
            Este plano aun no tiene anotaciones. Abre el editor para
            empezar.
          </p>
        ) : (
          <ul className="space-y-1">
            <li
              data-testid="plan-overlay-count-cajetin"
              className="flex items-center justify-between"
            >
              <span>{KIND_LABELS.cajetin}</span>
              <span className="font-mono">{summary.cajetin}</span>
            </li>
            <li
              data-testid="plan-overlay-count-legend"
              className="flex items-center justify-between"
            >
              <span>{KIND_LABELS.legend}</span>
              <span className="font-mono">{summary.legend}</span>
            </li>
            <li
              data-testid="plan-overlay-count-chat_facts"
              className="flex items-center justify-between"
            >
              <span>{KIND_LABELS.chat_facts}</span>
              <span className="font-mono">{summary.chatFacts}</span>
            </li>
            <li
              data-testid="plan-overlay-count-revision"
              className="flex items-center justify-between"
            >
              <span>{KIND_LABELS.revision}</span>
              <span className="font-mono">{summary.revisions}</span>
            </li>
          </ul>
        )}
        <Button asChild variant="outline" size="sm" className="w-full">
          <Link to={`/documents/${documentId}/annotate-plan`}>
            Abrir editor de anotaciones
          </Link>
        </Button>
      </CardContent>
    </Card>
  )
}
