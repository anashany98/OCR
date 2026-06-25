import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { PageHeader } from "@/components/layout/PageHeader"

import { NeedsReembeddingBanner, OcrDetails, OcrReviewFilters, OcrReviewQueue } from "./components"
import { useOcrReviewPage } from "./useOcrReviewPage"

/**
 * F8b - OCR review page composition.
 *
 * The page is now a thin wrapper that pulls data from
 * ``useOcrReviewPage`` and delegates layout to four section
 * components. The 2-col layout (queue + details) replaces the
 * previous vertical stack; the details panel uses tabs to keep
 * preview / OCR text / blocks in one place without dominating
 * the viewport.
 */
export function OcrReviewPage() {
  const data = useOcrReviewPage()

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumbs items={[{ label: "Revisión OCR" }]} />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <PageHeader
          title="Verificación OCR"
          description="Revisión humana de páginas con confianza OCR inferior al umbral."
        />
        <OcrReviewFilters data={data} />
      </div>

      <NeedsReembeddingBanner data={data} />

      <div className="grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        <OcrReviewQueue data={data} />
        <OcrDetails data={data} />
      </div>
    </div>
  )
}
