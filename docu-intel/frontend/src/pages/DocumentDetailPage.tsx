import { type ReactNode, useEffect, useMemo, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, Download, FileText, RefreshCcw, Save, Search } from "lucide-react"

import { api, downloadUrl, pageImageUrl } from "@/api/client"
import { EmptyState } from "@/components/layout/EmptyState"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatBytes, formatDate } from "@/lib/utils"
import type { DocumentPage, DocumentTimelineEvent } from "@/types/api"

export function DocumentDetailPage() {
  const id = Number(useParams().id)
  const queryClient = useQueryClient()
  const [selectedPageNumber, setSelectedPageNumber] = useState<number | null>(null)
  const [textQuery, setTextQuery] = useState("")
  const [editedText, setEditedText] = useState("")
  const [revisionReason, setRevisionReason] = useState("")
  const documentQuery = useQuery({ queryKey: ["document", id], queryFn: () => api.document(id), enabled: Number.isFinite(id) })
  const pagesQuery = useQuery({ queryKey: ["document-pages", id], queryFn: () => api.pages(id), enabled: Number.isFinite(id) })
  const blocksQuery = useQuery({ queryKey: ["document-blocks", id], queryFn: () => api.blocks(id), enabled: Number.isFinite(id) })
  const entitiesQuery = useQuery({ queryKey: ["document-entities", id], queryFn: () => api.entities(id), enabled: Number.isFinite(id) })
  const timelineQuery = useQuery({ queryKey: ["document-timeline", id], queryFn: () => api.documentTimeline(id), enabled: Number.isFinite(id) })
  const reprocess = useMutation({
    mutationFn: api.reprocess,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["document", id] })
      queryClient.invalidateQueries({ queryKey: ["document-pages", id] })
      queryClient.invalidateQueries({ queryKey: ["document-blocks", id] })
      queryClient.invalidateQueries({ queryKey: ["document-entities", id] })
    },
  })
  const document = documentQuery.data
  const pages = pagesQuery.data ?? []
  const selectedPage = useMemo(() => pages.find((page) => page.page_number === selectedPageNumber) ?? pages[0], [pages, selectedPageNumber])
  const revisionsQuery = useQuery({
    queryKey: ["ocr-revisions", selectedPage?.id],
    queryFn: () => api.ocrRevisions(selectedPage!.id),
    enabled: Boolean(selectedPage),
  })
  const visiblePages = useMemo(() => filterPages(pages, textQuery), [pages, textQuery])
  const timeline = useMemo(
    () => mergeTimeline(timelineQuery.data ?? [], buildTimeline(document, pages.length, entitiesQuery.data?.length ?? 0, blocksQuery.data?.length ?? 0)),
    [blocksQuery.data?.length, document, entitiesQuery.data?.length, pages.length, timelineQuery.data],
  )
  const saveRevision = useMutation({
    mutationFn: () =>
      api.createOcrRevision(selectedPage!.id, {
        corrected_text: editedText,
        reason: revisionReason.trim() || null,
      }),
    onSuccess: () => {
      setRevisionReason("")
      queryClient.invalidateQueries({ queryKey: ["document-pages", id] })
      queryClient.invalidateQueries({ queryKey: ["document-timeline", id] })
      queryClient.invalidateQueries({ queryKey: ["ocr-revisions", selectedPage?.id] })
    },
  })

  useEffect(() => {
    setEditedText(selectedPage?.text ?? "")
  }, [selectedPage?.id, selectedPage?.text])

  return (
    <>
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
        <div className="flex items-start gap-3">
          <Button asChild variant="outline" size="icon">
            <Link to="/documents">
              <ArrowLeft />
            </Link>
          </Button>
          <PageHeader title={document?.original_filename ?? "Documento"} description="Workspace documental con preview, OCR, entidades y trazabilidad básica." />
        </div>
        {document ? (
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => reprocess.mutate(document.id)} disabled={reprocess.isPending}>
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

      <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)_320px]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Preview</CardTitle>
            </CardHeader>
            <CardContent>
              {document && selectedPage?.image_path ? (
                <div className="overflow-hidden rounded-md border bg-slate-100">
                  <img className="max-h-[520px] w-full object-contain" src={pageImageUrl(document.id, selectedPage.page_number)} alt={`Página ${selectedPage.page_number}`} />
                </div>
              ) : (
                <EmptyState title="Sin preview visual" description="Este documento no tiene imagen de página disponible." icon={<FileText className="h-5 w-5" />} />
              )}
              {pages.length ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {pages.map((page) => (
                    <Button key={page.id} type="button" size="sm" variant={page.page_number === selectedPage?.page_number ? "default" : "outline"} onClick={() => setSelectedPageNumber(page.page_number)}>
                      P{page.page_number}
                    </Button>
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Metadatos</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2 text-sm">
              {document ? (
                <>
                  <Info label="Estado" value={<StatusBadge status={document.status} />} />
                  <Info label="Calidad" value={<StatusBadge status={document.quality_status ?? "-"} />} />
                  <Info label="Tipo" value={document.document_type} />
                  <Info label="Tamaño" value={formatBytes(document.file_size)} />
                  <Info label="Páginas" value={String((document.page_count ?? pages.length) || "-")} />
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
        </div>

        <Card className="min-w-0">
          <CardHeader className="flex-row items-center justify-between gap-3 border-b bg-slate-50/80">
            <CardTitle>Texto OCR</CardTitle>
            <div className="relative w-full max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input className="h-9 pl-8" value={textQuery} onChange={(event) => setTextQuery(event.target.value)} placeholder="Buscar dentro del documento" />
            </div>
          </CardHeader>
          <CardContent className="max-h-[760px] overflow-auto p-4">
            <div className="space-y-3">
              {visiblePages.map((page) => (
                <section key={page.id} className="rounded-md border bg-white p-3">
                  <div className="mb-2 flex justify-between text-xs text-muted-foreground">
                    <button className="font-medium text-primary" type="button" onClick={() => setSelectedPageNumber(page.page_number)}>
                      Página {page.page_number}
                    </button>
                    <span>OCR {page.ocr_confidence ? `${Math.round(page.ocr_confidence * 100)}%` : "-"}</span>
                  </div>
                  <pre className="whitespace-pre-wrap text-sm leading-6"><HighlightedText text={page.text || "Sin texto extraído."} query={textQuery} /></pre>
                </section>
              ))}
              {!visiblePages.length ? <EmptyState title="Sin coincidencias" description="No hay páginas que coincidan con la búsqueda actual." /> : null}
            </div>
            {selectedPage ? (
              <section className="mt-4 rounded-md border bg-slate-50 p-3">
                <div className="mb-2 flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold">Revisión OCR versionada</h3>
                    <p className="text-xs text-muted-foreground">
                      Página {selectedPage.page_number} · {revisionsQuery.data?.length ?? 0} revisiones guardadas
                    </p>
                  </div>
                  <Button
                    size="sm"
                    onClick={() => saveRevision.mutate()}
                    disabled={saveRevision.isPending || !editedText.trim() || editedText === (selectedPage.text ?? "")}
                  >
                    <Save data-icon="inline-start" />
                    Guardar versión
                  </Button>
                </div>
                <textarea
                  className="min-h-40 w-full rounded-md border bg-white p-3 font-mono text-sm leading-6 outline-none focus:ring-2 focus:ring-ring"
                  value={editedText}
                  onChange={(event) => setEditedText(event.target.value)}
                />
                <Input className="mt-2 h-9" value={revisionReason} onChange={(event) => setRevisionReason(event.target.value)} placeholder="Motivo de corrección" />
                {saveRevision.isError ? <p className="mt-2 text-sm text-destructive">{saveRevision.error.message}</p> : null}
              </section>
            ) : null}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Entidades</CardTitle>
            </CardHeader>
            <CardContent className="max-h-[300px] overflow-auto p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Valor</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(entitiesQuery.data ?? []).slice(0, 20).map((entity) => (
                    <TableRow key={entity.id}>
                      <TableCell><Badge variant="neutral">{entity.entity_type}</Badge></TableCell>
                      <TableCell className="max-w-[180px] truncate">{entity.entity_value}</TableCell>
                    </TableRow>
                  ))}
                  {!entitiesQuery.data?.length ? (
                    <TableRow>
                      <TableCell colSpan={2} className="h-16 text-center text-muted-foreground">
                        Sin entidades.
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Timeline</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {timeline.map((event, index) => (
                <div key={`${event.label}-${index}`} className="border-l-2 border-slate-200 pl-3">
                  <p className="text-sm font-medium">{event.label}</p>
                  <p className="text-xs text-muted-foreground">{event.value}</p>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Bloques OCR</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Info label="Total bloques" value={String(blocksQuery.data?.length ?? 0)} />
              <Info label="Página activa" value={selectedPage ? String(selectedPage.page_number) : "-"} />
              <Info label="Coincidencias" value={String(visiblePages.length)} />
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}

function Info({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  )
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  const trimmed = query.trim()
  if (!trimmed) return <>{text}</>
  const parts = text.split(new RegExp(`(${escapeRegExp(trimmed)})`, "gi"))
  return (
    <>
      {parts.map((part, index) =>
        part.toLowerCase() === trimmed.toLowerCase() ? (
          <mark key={`${part}-${index}`} className="rounded bg-amber-200 px-0.5">
            {part}
          </mark>
        ) : (
          <span key={`${part}-${index}`}>{part}</span>
        ),
      )}
    </>
  )
}

function filterPages(pages: DocumentPage[], query: string) {
  const trimmed = query.trim().toLowerCase()
  if (!trimmed) return pages
  return pages.filter((page) => page.text?.toLowerCase().includes(trimmed))
}

function buildTimeline(document: { created_at: string; processed_at: string | null; status: string } | undefined, pages: number, entities: number, blocks: number) {
  return [
    { label: "Registrado", value: formatDate(document?.created_at) },
    { label: "Procesamiento", value: document?.processed_at ? formatDate(document.processed_at) : document?.status ?? "-" },
    { label: "Páginas OCR", value: String(pages) },
    { label: "Entidades extraídas", value: String(entities) },
    { label: "Bloques detectados", value: String(blocks) },
  ]
}

function mergeTimeline(events: DocumentTimelineEvent[], fallback: { label: string; value: string }[]) {
  const operational = events.map((event) => ({
    label: event.title,
    value: `${formatDate(event.created_at)}${event.description ? ` · ${event.description}` : ""}`,
  }))
  return operational.length ? [...operational, ...fallback] : fallback
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}
