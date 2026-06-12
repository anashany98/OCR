import type { FormEvent } from "react"
import { RefreshCw } from "lucide-react"

import type {
  BulkTagsResponse,
  Document,
  OcrReviewPage,
  QualityRecalculateResponse,
  QualityRules,
  QualitySummary,
} from "@/types/api"
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

import { csv, ids, MetricBlock, optionalId } from "./shared"

interface MutationLike<TData = unknown> {
  mutate: () => void
  isPending: boolean
  data?: TData
  isError: boolean
  error: Error | null
}

interface AdminQualityTabProps {
  qualityRules?: QualityRules
  qualitySummary?: QualitySummary
  recalculateQuality: MutationLike<QualityRecalculateResponse>
  ocrReviewPages: OcrReviewPage[]
  duplicates: Document[]
  quarantine: Document[]
  tenantAdminEnabled: boolean
  bulkTagDocumentIds: string
  setBulkTagDocumentIds: (v: string) => void
  bulkTagAdd: string
  setBulkTagAdd: (v: string) => void
  bulkTagRemove: string
  setBulkTagRemove: (v: string) => void
  applyBulkTags: MutationLike<BulkTagsResponse>
  assignDocumentId: string
  setAssignDocumentId: (v: string) => void
  assignChainId: string
  setAssignChainId: (v: string) => void
  assignHotelId: string
  setAssignHotelId: (v: string) => void
  assignTags: string
  setAssignTags: (v: string) => void
  chains: { id: number; name: string }[]
  hotels: { id: number; name: string }[]
  updateDocumentAccess: MutationLike
}

export function AdminQualityTab({
  qualityRules,
  qualitySummary,
  recalculateQuality,
  ocrReviewPages,
  duplicates,
  quarantine,
  tenantAdminEnabled,
  bulkTagDocumentIds,
  setBulkTagDocumentIds,
  bulkTagAdd,
  setBulkTagAdd,
  bulkTagRemove,
  setBulkTagRemove,
  applyBulkTags,
  assignDocumentId,
  setAssignDocumentId,
  assignChainId,
  setAssignChainId,
  assignHotelId,
  setAssignHotelId,
  assignTags,
  setAssignTags,
  chains,
  hotels,
  updateDocumentAccess,
}: AdminQualityTabProps) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3">
          <CardTitle>Calidad de datos</CardTitle>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => recalculateQuality.mutate()}
            disabled={recalculateQuality.isPending}
          >
            <RefreshCw data-icon="inline-start" />
            Recalcular
          </Button>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="grid gap-2 md:grid-cols-3">
            {Object.entries(qualitySummary?.rules ?? {}).map(([key, value]) => (
              <div key={key} className="rounded-md border p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium">{key}</p>
                  <Badge variant={value.count > 0 ? "warning" : "outline"}>{value.count}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{value.description}</p>
              </div>
            ))}
          </div>
          <MetricBlock title="Estados de calidad" values={qualitySummary?.by_quality_status} />
          <p className="text-xs text-muted-foreground">
            Umbral OCR bajo:{" "}
            {qualityRules?.low_ocr_threshold != null
              ? Math.round(qualityRules.low_ocr_threshold * 100) + "%"
              : "-"}
          </p>
          {recalculateQuality.data ? (
            <p className="text-sm text-muted-foreground">
              Recalculados: {recalculateQuality.data.updated}. En revisi&oacute;n:{" "}
              {recalculateQuality.data.needs_review}.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Revisi&oacute;n OCR</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-h-96 overflow-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID P&aacute;gina</TableHead>
                  <TableHead>Documento</TableHead>
                  <TableHead>Confianza</TableHead>
                  <TableHead>Estado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {ocrReviewPages.map((page) => (
                  <TableRow key={page.page_id}>
                    <TableCell>{page.page_id}</TableCell>
                    <TableCell className="max-w-[260px] truncate">
                      {page.original_filename}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          page.ocr_confidence != null && page.ocr_confidence < 0.7
                            ? "warning"
                            : "outline"
                        }
                      >
                        {page.ocr_confidence != null
                          ? Math.round(page.ocr_confidence * 100) + "%"
                          : "-"}
                      </Badge>
                    </TableCell>
                    <TableCell>{page.review_status}</TableCell>
                  </TableRow>
                ))}
                {!ocrReviewPages.length ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground">
                      Sin p&aacute;ginas en revisi&oacute;n.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Documentos duplicados</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-h-96 overflow-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Documento</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Estado</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {duplicates.map((doc) => (
                  <TableRow key={doc.id}>
                    <TableCell>{doc.id}</TableCell>
                    <TableCell className="max-w-[260px] truncate">
                      {doc.original_filename}
                    </TableCell>
                    <TableCell>{doc.document_type}</TableCell>
                    <TableCell>{doc.status}</TableCell>
                  </TableRow>
                ))}
                {!duplicates.length ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground">
                      Sin duplicados detectados.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {tenantAdminEnabled ? (
        <Card>
          <CardHeader>
            <CardTitle>Documentos en cuarentena</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <form
              className="grid gap-2 lg:grid-cols-[120px_180px_180px_1fr_auto]"
              onSubmit={(event: FormEvent) => {
                event.preventDefault()
                if (assignDocumentId) updateDocumentAccess.mutate()
              }}
            >
              <Input
                value={assignDocumentId}
                onChange={(event) => setAssignDocumentId(event.target.value)}
                placeholder="Doc ID"
              />
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={assignChainId}
                onChange={(event) => setAssignChainId(event.target.value)}
              >
                <option value="">Cadena</option>
                {chains.map((chain) => (
                  <option key={chain.id} value={chain.id}>
                    {chain.name}
                  </option>
                ))}
              </select>
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={assignHotelId}
                onChange={(event) => setAssignHotelId(event.target.value)}
              >
                <option value="">Hotel</option>
                {hotels.map((hotel) => (
                  <option key={hotel.id} value={hotel.id}>
                    {hotel.name}
                  </option>
                ))}
              </select>
              <Input
                value={assignTags}
                onChange={(event) => setAssignTags(event.target.value)}
                placeholder="tags manuales"
              />
              <Button disabled={updateDocumentAccess.isPending}>Asignar</Button>
            </form>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Documento</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Origen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {quarantine.map((document) => (
                  <TableRow key={document.id}>
                    <TableCell>{document.id}</TableCell>
                    <TableCell>{document.original_filename}</TableCell>
                    <TableCell>{document.document_type}</TableCell>
                    <TableCell className="max-w-[360px] truncate">
                      {document.source_path ?? "-"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Tags en lote</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <form
            className="grid gap-2"
            onSubmit={(event: FormEvent) => {
              event.preventDefault()
              if (ids(bulkTagDocumentIds).length) {
                if (
                  window.confirm(
                    "¿Aplicar tags en lote a " + ids(bulkTagDocumentIds).length + " documentos?",
                  )
                ) {
                  applyBulkTags.mutate()
                }
              }
            }}
          >
            <Input
              value={bulkTagDocumentIds}
              onChange={(event) => setBulkTagDocumentIds(event.target.value)}
              placeholder="IDs documento: 12,15,18"
            />
            <Input
              value={bulkTagAdd}
              onChange={(event) => setBulkTagAdd(event.target.value)}
              placeholder="A&ntilde;adir tags"
            />
            <Input
              value={bulkTagRemove}
              onChange={(event) => setBulkTagRemove(event.target.value)}
              placeholder="Quitar tags"
            />
            <Button disabled={applyBulkTags.isPending}>Aplicar tags</Button>
          </form>
          {applyBulkTags.data ? (
            <p className="text-muted-foreground">Actualizados: {applyBulkTags.data.updated}</p>
          ) : null}
          {applyBulkTags.isError ? (
            <p className="text-sm text-destructive">{applyBulkTags.error?.message}</p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
