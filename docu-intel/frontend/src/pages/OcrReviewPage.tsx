import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ExternalLink, RefreshCcw, RotateCw, X } from "lucide-react"
import { useMemo, useState } from "react"

import { api, pageImageUrl } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn, formatDate } from "@/lib/utils"
import type { OcrReviewPage } from "@/types/api"

export function OcrReviewPage() {
  const queryClient = useQueryClient()
  const [thresholdPercent, setThresholdPercent] = useState("70")
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const threshold = useMemo(() => {
    const numeric = Number(thresholdPercent)
    if (!Number.isFinite(numeric)) return 0.7
    return Math.min(Math.max(numeric, 0), 100) / 100
  }, [thresholdPercent])
  const reviewQuery = useQuery({
    queryKey: ["ocr-review", threshold],
    queryFn: () => api.ocrReview({ max_confidence: threshold, limit: 200 }),
  })
  const reviewItems = reviewQuery.data ?? []
  const selected = reviewItems.find((item) => reviewKey(item) === selectedKey) ?? reviewItems[0] ?? null
  const reprocess = useMutation({
    mutationFn: (documentId: number) => api.reprocessOCR(documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ocr-review"] })
      queryClient.invalidateQueries({ queryKey: ["jobs"] })
      queryClient.invalidateQueries({ queryKey: ["stats"] })
    },
  })
  const reviewMutation = useMutation({
    mutationFn: ({ pageId, reviewStatus }: { pageId: number; reviewStatus: "approved" | "rejected" }) =>
      api.updateOcrReview(pageId, { review_status: reviewStatus }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ocr-review"] })
      queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
      queryClient.invalidateQueries({ queryKey: ["stats"] })
    },
  })

  return (
    <>
      <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
        <PageHeader title="Verificación OCR" description="Revisión humana de páginas con confianza OCR inferior al umbral seleccionado." />
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-sm text-muted-foreground" htmlFor="ocr-threshold">
            Umbral %
          </label>
          <Input
            className="w-24"
            id="ocr-threshold"
            max="100"
            min="0"
            onChange={(event) => setThresholdPercent(event.target.value)}
            step="5"
            type="number"
            value={thresholdPercent}
          />
          <Button variant="outline" onClick={() => reviewQuery.refetch()} disabled={reviewQuery.isFetching}>
            <RotateCw data-icon="inline-start" />
            Actualizar
          </Button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[440px_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Cola de revisión</CardTitle>
            <CardDescription>{reviewItems.length} páginas por debajo de {Math.round(threshold * 100)}%.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-h-[680px] overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Documento</TableHead>
                    <TableHead>Página</TableHead>
                    <TableHead>OCR</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reviewItems.map((item) => (
                    <TableRow
                      className={cn("cursor-pointer", selected && reviewKey(selected) === reviewKey(item) && "bg-muted")}
                      key={reviewKey(item)}
                      onClick={() => setSelectedKey(reviewKey(item))}
                    >
                      <TableCell className="max-w-[250px]">
                        <div className="flex flex-col gap-1">
                          <span className="truncate font-medium">{item.original_filename}</span>
                          <span className="text-xs text-muted-foreground">{item.document_type}</span>
                        </div>
                      </TableCell>
                      <TableCell>{item.page_number}</TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <ConfidenceBadge value={item.ocr_confidence} />
                          <ReviewBadge status={item.review_status} />
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!reviewItems.length ? (
                    <TableRow>
                      <TableCell colSpan={3} className="h-24 text-center text-muted-foreground">
                        No hay páginas OCR por debajo del umbral.
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-4">
          <Card>
            <CardHeader className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="flex flex-col gap-1.5">
                <CardTitle>{selected?.original_filename ?? "Sin página seleccionada"}</CardTitle>
                {selected ? (
                  <CardDescription>
                    Página {selected.page_number} · OCR {formatPercent(selected.ocr_confidence)} · {formatDate(selected.created_at)}
                  </CardDescription>
                ) : null}
              </div>
              {selected ? (
                <div className="flex flex-wrap gap-2">
                  <StatusBadge status={selected.status} />
                  <ReviewBadge status={selected.review_status} />
                  <Button asChild variant="outline" size="sm">
                    <Link to={"/documents/" + selected.document_id}>
                      <ExternalLink data-icon="inline-start" />
                      Abrir documento
                    </Link>
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={reviewMutation.isPending || selected.review_status === "approved"}
                    onClick={() => reviewMutation.mutate({ pageId: selected.page_id, reviewStatus: "approved" })}
                  >
                    <Check data-icon="inline-start" />
                    Aprobar
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={reviewMutation.isPending || selected.review_status === "rejected"}
                    onClick={() => reviewMutation.mutate({ pageId: selected.page_id, reviewStatus: "rejected" })}
                  >
                    <X data-icon="inline-start" />
                    Denegar
                  </Button>
                  <Button variant="outline" size="sm" disabled={reprocess.isPending} onClick={() => reprocess.mutate(selected.document_id)}>
                    <RefreshCcw data-icon="inline-start" />
                    Reprocesar OCR
                  </Button>
                </div>
              ) : null}
            </CardHeader>
            <CardContent>
              {selected?.preview_url ? (
                <div className="flex min-h-[380px] items-center justify-center overflow-auto rounded-md border bg-muted">
                  <img
                    alt={"Preview OCR página " + selected.page_number}
                    className="max-h-[720px] w-full object-contain"
                    src={pageImageUrl(selected.document_id, selected.page_number)}
                  />
                </div>
              ) : (
                <div className="flex min-h-[280px] items-center justify-center rounded-md border text-sm text-muted-foreground">
                  No hay imagen de preview para esta página.
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>OCR extraído</CardTitle>
              <CardDescription>Texto completo guardado para la página seleccionada.</CardDescription>
            </CardHeader>
            <CardContent>
              <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap rounded-md border bg-muted p-3 text-sm leading-6">
                {selected?.text || "Sin texto OCR disponible."}
              </pre>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}

function reviewKey(item: OcrReviewPage) {
  return item.document_id + ":" + item.page_number
}

function formatPercent(value: number | null) {
  return value === null ? "-" : Math.round(value * 100) + "%"
}

function ConfidenceBadge({ value }: { value: number | null }) {
  if (value === null) return <Badge variant="outline">-</Badge>
  return <Badge variant={value < 0.5 ? "destructive" : "warning"}>{formatPercent(value)}</Badge>
}

function ReviewBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    pending: "pendiente",
    approved: "aprobado",
    rejected: "denegado",
  }
  const variant = status === "approved" ? "success" : status === "rejected" ? "destructive" : "outline"
  return <Badge variant={variant}>{labels[status] ?? status}</Badge>
}
