import { Link, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ArrowLeft, Download, RefreshCcw } from "lucide-react"

import { api, downloadUrl } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatBytes, formatDate } from "@/lib/utils"

export function DocumentDetailPage() {
  const id = Number(useParams().id)
  const documentQuery = useQuery({ queryKey: ["document", id], queryFn: () => api.document(id), enabled: Number.isFinite(id) })
  const pagesQuery = useQuery({ queryKey: ["document-pages", id], queryFn: () => api.pages(id), enabled: Number.isFinite(id) })
  const blocksQuery = useQuery({ queryKey: ["document-blocks", id], queryFn: () => api.blocks(id), enabled: Number.isFinite(id) })
  const entitiesQuery = useQuery({ queryKey: ["document-entities", id], queryFn: () => api.entities(id), enabled: Number.isFinite(id) })
  const document = documentQuery.data

  return (
    <>
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
        <div className="flex items-start gap-3">
          <Button asChild variant="outline" size="icon">
            <Link to="/documents">
              <ArrowLeft />
            </Link>
          </Button>
          <PageHeader title={document?.original_filename ?? "Documento"} description="Texto extraído, bloques OCR y estado de procesamiento." />
        </div>
        {document ? (
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => api.reprocess(document.id)}>
              <RefreshCcw data-icon="inline-start" />
              Reprocesar
            </Button>
            <Button asChild>
              <a href={downloadUrl(document.id)}>
                <Download data-icon="inline-start" />
                Descargar original
              </a>
            </Button>
          </div>
        ) : null}
      </div>

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Metadatos</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            {document ? (
              <>
                <div className="flex justify-between gap-3">
                  <span className="text-muted-foreground">Estado</span>
                  <StatusBadge status={document.status} />
                </div>
                <Info label="Tipo" value={document.document_type} />
                <Info label="Tamaño" value={formatBytes(document.file_size)} />
                <Info label="Páginas" value={String(document.page_count ?? "-")} />
                <Info label="Confianza" value={document.confidence ? `${Math.round(document.confidence * 100)}%` : "-"} />
                <Info label="Creado" value={formatDate(document.created_at)} />
                <Info label="Procesado" value={formatDate(document.processed_at)} />
                {document.error_message ? <p className="rounded-md border border-destructive/40 p-2 text-destructive">{document.error_message}</p> : null}
              </>
            ) : (
              <span className="text-muted-foreground">Cargando...</span>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Texto extraído</CardTitle>
          </CardHeader>
          <CardContent className="flex max-h-[560px] flex-col gap-4 overflow-auto">
            {(pagesQuery.data ?? []).map((page) => (
              <section key={page.id} className="rounded-md border p-3">
                <div className="mb-2 flex justify-between text-xs text-muted-foreground">
                  <span>Página {page.page_number}</span>
                  <span>OCR {page.ocr_confidence ? `${Math.round(page.ocr_confidence * 100)}%` : "-"}</span>
                </div>
                <pre className="whitespace-pre-wrap text-sm leading-6">{page.text || "Sin texto extraído."}</pre>
              </section>
            ))}
            {!pagesQuery.data?.length ? <p className="text-sm text-muted-foreground">No hay páginas registradas.</p> : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Entidades detectadas</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tipo</TableHead>
                <TableHead>Valor</TableHead>
                <TableHead>Confianza</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(entitiesQuery.data ?? []).map((entity) => (
                <TableRow key={entity.id}>
                  <TableCell>{entity.entity_type}</TableCell>
                  <TableCell>{entity.entity_value}</TableCell>
                  <TableCell>{entity.confidence ? `${Math.round(entity.confidence * 100)}%` : "-"}</TableCell>
                </TableRow>
              ))}
              {!entitiesQuery.data?.length ? (
                <TableRow>
                  <TableCell colSpan={3} className="h-16 text-center text-muted-foreground">
                    Sin entidades detectadas.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Bloques OCR</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Página</TableHead>
                <TableHead>Motor</TableHead>
                <TableHead>Confianza</TableHead>
                <TableHead>Texto</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(blocksQuery.data ?? []).map((block) => (
                <TableRow key={block.id}>
                  <TableCell>{block.page_number ?? "-"}</TableCell>
                  <TableCell>{block.source_engine ?? "-"}</TableCell>
                  <TableCell>{block.confidence ? `${Math.round(block.confidence * 100)}%` : "-"}</TableCell>
                  <TableCell className="max-w-3xl">{block.text}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  )
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  )
}
