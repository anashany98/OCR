import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, ExternalLink, RefreshCcw, RotateCw, Sparkles, X } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { api, pageImageUrl } from "@/api/client"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn, formatDate } from "@/lib/utils"
import { notify } from "@/lib/toast"
import type { OcrReviewPage } from "@/types/api"

export function OcrReviewPage() {
  const queryClient = useQueryClient()
  const [thresholdPercent, setThresholdPercent] = useState("70")
  const [documentType, setDocumentType] = useState("")
  const [statusFilter, setStatusFilter] = useState("")
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [reviewNotes, setReviewNotes] = useState("")
  const threshold = useMemo(() => {
    const numeric = Number(thresholdPercent)
    if (!Number.isFinite(numeric)) return 0.7
    return Math.min(Math.max(numeric, 0), 100) / 100
  }, [thresholdPercent])
  const reviewQuery = useQuery({
    queryKey: ["ocr-review", threshold, documentType, statusFilter],
    queryFn: () => api.ocrReview({ max_confidence: threshold, document_type: documentType || undefined, status: statusFilter || undefined, limit: 200 }),
  })
  const reviewItems = reviewQuery.data ?? []
  const selected = reviewItems.find((item) => reviewKey(item) === selectedKey) ?? reviewItems[0] ?? null
  useEffect(() => {
    setReviewNotes(selected?.review_notes ?? "")
  }, [selected?.page_id])
  const reprocess = useMutation({
    mutationFn: (pageId: number) => api.reprocessOcrPage(pageId),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["ocr-review"] })
      queryClient.invalidateQueries({ queryKey: ["jobs"] })
      queryClient.invalidateQueries({ queryKey: ["stats"] })
      notify.success(`Reprocesamiento OCR encolado`, `Job #${job.id} creado.`)
    },
    onError: (err) => notify.error(err, "No se pudo reprocesar la página"),
  })
  const reviewMutation = useMutation({
    mutationFn: ({ pageId, reviewStatus, notes }: { pageId: number; reviewStatus: "approved" | "rejected"; notes?: string }) =>
      api.updateOcrReview(pageId, { review_status: reviewStatus, review_notes: notes || null }),
    onSuccess: (_, vars) => {
      setReviewNotes("")
      queryClient.invalidateQueries({ queryKey: ["ocr-review"] })
      queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
      queryClient.invalidateQueries({ queryKey: ["stats"] })
      const label = vars.reviewStatus === "approved" ? "aprobada" : "denegada"
      notify.success(`Página ${label}`)
    },
    onError: (err) => notify.error(err, "No se pudo registrar la revisión"),
  })
  const reembed = useMutation({
    mutationFn: (documentId: number) => api.reembedDocument(documentId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["ocr-review"] })
      queryClient.invalidateQueries({ queryKey: ["audit-logs"] })
      queryClient.invalidateQueries({ queryKey: ["stats"] })
      queryClient.invalidateQueries({ queryKey: ["documents"] })
      queryClient.invalidateQueries({ queryKey: ["needs-reembedding"] })
      const embedded = result.chunks_with_embedding
      const pending = result.chunks_needing_reembedding
      if (pending === 0) {
        notify.success(
          `Re-embedding completado`,
          `${embedded} chunks re-embedidos con ${result.provider}.`,
        )
      } else {
        notify.warning(
          `Re-embedding parcial`,
          `${embedded} chunks con embedding, ${pending} aún pendientes. Revisa el provider.`,
        )
      }
    },
    onError: (err) => notify.error(err, "No se pudo re-embebir el documento"),
  })
  const needsReembeddingQuery = useQuery({
    queryKey: ["needs-reembedding"],
    queryFn: () => api.documentsNeedingReembedding({ limit: 50 }),
    refetchInterval: 30_000,
  })
  const needsReembedding = needsReembeddingQuery.data ?? []

  return (
    <>
      <Breadcrumbs items={[{ label: "Revisión OCR" }]} />

      {needsReembedding.length > 0 ? (
        <Card className="border-amber-500/50 bg-amber-50/30 dark:bg-amber-950/20">
          <CardHeader>
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-amber-600" />
                  Documentos que necesitan re-embedding
                </CardTitle>
                <CardDescription>
                  {needsReembedding.length} documento(s) con chunks sin embedding
                  (el provider de embeddings falló durante el procesamiento inicial).
                  Usa el botón para regenerar embeddings sin re-OCR.
                </CardDescription>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => needsReembeddingQuery.refetch()}
                disabled={needsReembeddingQuery.isFetching}
              >
                <RotateCw data-icon="inline-start" />
                Actualizar
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <div className="max-h-72 overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Documento</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Chunks pendientes</TableHead>
                    <TableHead className="text-right">Acción</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {needsReembedding.map((doc) => (
                    <TableRow key={doc.document_id}>
                      <TableCell className="font-medium">
                        <Link
                          className="hover:underline"
                          to={`/documents/${doc.document_id}`}
                        >
                          {doc.original_filename}
                        </Link>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {doc.document_type ?? "—"}
                      </TableCell>
                      <TableCell>
                        <Badge variant="warning">
                          {doc.chunks_needing_reembedding} / {doc.chunks_total}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={reembed.isPending}
                          onClick={() => reembed.mutate(doc.document_id)}
                        >
                          <Sparkles data-icon="inline-start" />
                          {reembed.isPending && reembed.variables === doc.document_id
                            ? "Re-embediendo…"
                            : "Re-embebir"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      ) : null}

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
          <select className="h-9 rounded-md border bg-background px-3 text-sm" value={documentType} onChange={(event) => setDocumentType(event.target.value)}>
            <option value="">Tipo</option>
            <option value="presupuesto">Presupuesto</option>
            <option value="pedido">Pedido</option>
            <option value="factura">Factura</option>
            <option value="plano">Plano</option>
            <option value="imagen">Imagen</option>
            <option value="excel">Excel</option>
          </select>
          <select className="h-9 rounded-md border bg-background px-3 text-sm" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">Estado</option>
            <option value="needs_review">Revisión</option>
            <option value="processed">Procesado</option>
            <option value="failed">Fallido</option>
          </select>
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
                  <Button variant="outline" size="sm" disabled={reviewMutation.isPending || selected.review_status === "approved"} onClick={() => reviewMutation.mutate({ pageId: selected.page_id, reviewStatus: "approved", notes: reviewNotes })}>
                    <Check data-icon="inline-start" />
                    Aprobar
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    disabled={reviewMutation.isPending || selected.review_status === "rejected" || !reviewNotes.trim()}
                    onClick={() => reviewMutation.mutate({ pageId: selected.page_id, reviewStatus: "rejected", notes: reviewNotes })}
                  >
                    <X data-icon="inline-start" />
                    Denegar
                  </Button>
                  <Button variant="outline" size="sm" disabled={reprocess.isPending} onClick={() => reprocess.mutate(selected.page_id)}>
                    <RefreshCcw data-icon="inline-start" />
                    Reprocesar OCR
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={reembed.isPending}
                    onClick={() => reembed.mutate(selected.document_id)}
                    title="Vuelve a generar los embeddings de todos los chunks del documento. Útil cuando el embedding falló durante el procesamiento inicial."
                  >
                    <Sparkles data-icon="inline-start" />
                    {reembed.isPending ? "Re-embediendo…" : "Re-embebir documento"}
                  </Button>
                </div>
              ) : null}
            </CardHeader>
            <CardContent>
              {selected ? (
                <div className="mb-3 grid gap-2">
                  <textarea
                    className="min-h-20 rounded-md border bg-background px-3 py-2 text-sm"
                    onChange={(event) => setReviewNotes(event.target.value)}
                    placeholder="Motivo o nota de revisión. Obligatorio al denegar."
                    value={reviewNotes}
                  />
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline">Calidad: {selected.quality_status}</Badge>
                    {selected.quality_score != null ? <Badge variant="outline">Score {Math.round(selected.quality_score * 100)}%</Badge> : null}
                    {selected.quality_flags_json.map((flag) => (
                      <Badge key={flag} variant="warning">
                        {flag}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : null}
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

          <Card>
            <CardHeader>
              <CardTitle>Bloques OCR</CardTitle>
              <CardDescription>Bloques y confianza detectados por el motor OCR.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="max-h-[360px] overflow-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Tipo</TableHead>
                      <TableHead>Confianza</TableHead>
                      <TableHead>Texto</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(selected?.blocks ?? []).map((block) => (
                      <TableRow key={block.id}>
                        <TableCell>{block.block_type}</TableCell>
                        <TableCell>{formatPercent(block.confidence)}</TableCell>
                        <TableCell className="max-w-[520px] whitespace-pre-wrap">{block.text ?? "-"}</TableCell>
                      </TableRow>
                    ))}
                    {!(selected?.blocks ?? []).length ? (
                      <TableRow>
                        <TableCell colSpan={3} className="h-20 text-center text-muted-foreground">
                          No hay bloques OCR para esta página.
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </TableBody>
                </Table>
              </div>
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
