import { ChangeEvent, useCallback, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, CheckCircle2, Download, Eye, FileSpreadsheet, FolderUp, Loader2, RefreshCcw, Search, Upload, X } from "lucide-react"

import { api, downloadUrl } from "@/api/client"
import { EmptyState } from "@/components/layout/EmptyState"
import { PageHeader } from "@/components/layout/PageHeader"
import { PageToolbar } from "@/components/layout/PageToolbar"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { applyDocumentView, documentViews, type DocumentViewId } from "@/lib/documentViews"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { EmptyDocumentsIllustration } from "@/components/illustrations/EditorialIllustrations"
import { notify } from "@/lib/toast"
import { formatBytes, formatDate } from "@/lib/utils"
import type { Document } from "@/types/api"

const pageSize = 25
const statusOptions = ["", "pending", "processing", "processed", "needs_review", "failed", "duplicate"]
const typeOptions = ["", "presupuesto", "pedido", "factura", "plano", "imagen", "excel", "otro"]

export function DocumentsPage() {
  const queryClient = useQueryClient()
  const [view, setView] = useState<DocumentViewId>("all")
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState("")
  const [documentType, setDocumentType] = useState("")
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<number[]>([])
  const [isDragging, setIsDragging] = useState(false)

  const params = useMemo(() => {
    const viewFilters = applyDocumentView(view, { q: query, limit: pageSize, offset })
    return {
      ...viewFilters,
      status: status || viewFilters.status,
      document_type: documentType || viewFilters.document_type,
    }
  }, [documentType, offset, query, status, view])

  const documents = useQuery({ queryKey: ["documents", "operations", params], queryFn: () => api.operationsDocuments(params) })
  const rows = documents.data?.items ?? []
  const total = documents.data?.total ?? 0
  const selectedSet = useMemo(() => new Set(selected), [selected])

  const upload = useMutation({
    mutationFn: api.upload,
    onSuccess: () => {
      invalidateDocuments(queryClient)
      notify.success("Documento subido", "Se ha encolado para procesamiento.")
    },
    onError: (err) => notify.error(err, "Error al subir el archivo"),
  })
  const uploadBatch = useMutation({
    mutationFn: (payload: { files: File[]; relativePaths?: string[] }) =>
      api.uploadBatch(payload.files, payload.relativePaths),
    onSuccess: (data) => {
      invalidateDocuments(queryClient)
      notify.success(
        "Subida completada",
        `${data.uploaded} nuevo(s), ${data.duplicates} duplicado(s), ${data.failed} fallido(s).`,
      )
    },
    onError: (err) => notify.error(err, "Error al subir archivos"),
  })
  const scan = useMutation({
    mutationFn: api.scan,
    onSuccess: (data) => {
      invalidateDocuments(queryClient)
      notify.success(
        "Escaneo completado",
        `${data.registered} nuevos, ${data.duplicates} duplicados, ${data.skipped} saltados.`,
      )
    },
    onError: (err) => notify.error(err, "Error al escanear"),
  })
  const reprocess = useMutation({
    mutationFn: api.reprocess,
    onSuccess: (job) => {
      invalidateDocuments(queryClient)
      notify.success(`Reprocesamiento encolado`, `Job #${job.id} creado.`)
    },
    onError: (err) => notify.error(err, "Error al reprocesar"),
  })
  const bulkReprocess = useMutation({
    mutationFn: api.reprocessBulk,
    onSuccess: (data) => {
      setSelected([])
      invalidateDocuments(queryClient)
      notify.success(
        "Reprocesamiento en lote",
        `${data.enqueued} jobs encolados, ${data.matched} documentos encontrados.`,
      )
    },
    onError: (err) => notify.error(err, "Error al reprocesar en lote"),
  })

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
      setIsDragging(false)
      const files = Array.from(event.dataTransfer.files)
      if (files.length) uploadBatch.mutate({ files })
    },
    [uploadBatch],
  )

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files
    if (files && files.length > 0) {
      if (files.length === 1) upload.mutate(files[0])
      else uploadBatch.mutate({ files: Array.from(files) })
    }
    event.target.value = ""
  }

  function onFolderChange(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files
    if (files && files.length > 0) {
      // webkitRelativePath preserves the folder structure selected by the user,
      // e.g. "presupuestos/245745/foo.pdf" — the backend stores it in
      // documents.source_path so the IA can use it as a classification hint.
      const fileArray = Array.from(files)
      const relativePaths = fileArray.map(
        (f) => (f as File & { webkitRelativePath?: string }).webkitRelativePath ?? f.name,
      )
      uploadBatch.mutate({ files: fileArray, relativePaths })
    }
    event.target.value = ""
  }

  function changeView(nextView: DocumentViewId) {
    setView(nextView)
    setStatus("")
    setDocumentType("")
    setOffset(0)
    setSelected([])
  }

  function toggleSelected(documentId: number) {
    setSelected((current) => (current.includes(documentId) ? current.filter((id) => id !== documentId) : [...current, documentId]))
  }

  function togglePage() {
    const rowIds = rows.map((document) => document.id)
    const allSelected = rowIds.length > 0 && rowIds.every((id) => selectedSet.has(id))
    setSelected((current) => (allSelected ? current.filter((id) => !rowIds.includes(id)) : Array.from(new Set([...current, ...rowIds]))))
  }

  return (
    <div className="flex flex-col gap-4" onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}>
      <Breadcrumbs items={[{ label: "Documentos" }]} />
      <PageHeader
        title="Documentos"
        description="Tabla operativa con filtros de servidor, vistas guardadas y acciones masivas."
        actions={
          <>
            <Button variant="outline" onClick={() => scan.mutate()} disabled={scan.isPending}>
              <RefreshCcw data-icon="inline-start" />
              Escanear carpetas
            </Button>
            <Button asChild>
              <label>
                <Upload data-icon="inline-start" />
                Subir
                <input className="hidden" type="file" multiple onChange={onFileChange} />
              </label>
            </Button>
            <Button asChild variant="outline">
              <label>
                <FolderUp data-icon="inline-start" />
                Subir carpeta
                <input
                  className="hidden"
                  type="file"
                  /* @ts-expect-error - non-standard but supported in Chrome/Edge/Firefox/Safari */
                  webkitdirectory=""
                  directory=""
                  multiple
                  onChange={onFolderChange}
                />
              </label>
            </Button>
          </>
        }
      />

      {isDragging ? (
        <div className="flex items-center justify-center rounded-md border-2 border-dashed border-primary bg-primary/5 py-8">
          <div className="flex flex-col items-center gap-2 text-primary">
            <Upload className="h-8 w-8" />
            <span className="font-medium">Suelta archivos para subir</span>
          </div>
        </div>
      ) : null}

      <PageToolbar>
        <div className="flex flex-1 flex-wrap gap-2">
          {documentViews.map((item) => (
            <Button key={item.id} type="button" variant={item.id === view ? "default" : "outline"} size="sm" onClick={() => changeView(item.id)}>
              {item.label}
            </Button>
          ))}
        </div>
        <div className="relative min-w-[220px] flex-1 md:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            className="h-9 pl-8"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setOffset(0)
            }}
            placeholder="Archivo, proveedor, referencia..."
          />
        </div>
        <select className="h-9 rounded-md border bg-background px-3 text-sm" value={status} onChange={(event) => { setStatus(event.target.value); setOffset(0) }}>
          {statusOptions.map((option) => (
            <option key={option} value={option}>{option || "Estado"}</option>
          ))}
        </select>
        <select className="h-9 rounded-md border bg-background px-3 text-sm" value={documentType} onChange={(event) => { setDocumentType(event.target.value); setOffset(0) }}>
          {typeOptions.map((option) => (
            <option key={option} value={option}>{option || "Tipo"}</option>
          ))}
        </select>
      </PageToolbar>

      {(upload.isPending || uploadBatch.isPending) ? (
        <div
          role="status"
          aria-live="polite"
          data-testid="upload-status-pending"
          className="flex items-center gap-2 rounded-md border border-[var(--info)]/20 bg-[var(--info-faint)] px-4 py-3 text-sm text-[var(--text-on-info)]"
        >
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>
            {upload.isPending
              ? "Subiendo archivo..."
              : `Subiendo ${uploadBatch.variables?.files?.length ?? "varios"} archivo(s)...`}
          </span>
        </div>
      ) : null}

      {(upload.isError || uploadBatch.isError) ? (
        <div
          role="alert"
          data-testid="upload-status-error"
          className="flex items-center justify-between gap-2 rounded-md border border-[var(--danger)]/20 bg-[var(--danger-faint)] px-4 py-3 text-sm text-[var(--text-on-danger)]"
        >
          <div className="flex min-w-0 items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span className="truncate">
              Error al subir: {upload.error?.message ?? uploadBatch.error?.message ?? "fallo desconocido"}
            </span>
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              upload.reset()
              uploadBatch.reset()
            }}
          >
            <X data-icon="inline-start" className="h-4 w-4" />
            Cerrar
          </Button>
        </div>
      ) : null}

      {upload.isSuccess ? (
        <div
          role="status"
          aria-live="polite"
          data-testid="upload-status-success-single"
          className="flex items-center justify-between gap-2 rounded-md border border-[var(--positive)]/20 bg-[var(--positive-faint)] px-4 py-3 text-sm text-[var(--text-on-success)]"
        >
          <div className="flex min-w-0 items-center gap-2">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            <span className="truncate">Archivo subido correctamente.</span>
          </div>
          <Button size="sm" variant="ghost" onClick={() => upload.reset()}>
            <X data-icon="inline-start" className="h-4 w-4" />
            Cerrar
          </Button>
        </div>
      ) : null}

      {uploadBatch.isSuccess && uploadBatch.data ? (
        <div
          role="status"
          aria-live="polite"
          data-testid="upload-status-success-batch"
          className="flex items-center justify-between gap-2 rounded-md border border-[var(--positive)]/20 bg-[var(--positive-faint)] px-4 py-3 text-sm text-[var(--text-on-success)]"
        >
          <div className="flex min-w-0 items-center gap-2">
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            <span className="truncate">
              Subida completada: {uploadBatch.data.uploaded} nuevo(s), {uploadBatch.data.duplicates}{" "}
              duplicado(s), {uploadBatch.data.failed} fallido(s).
            </span>
          </div>
          <Button size="sm" variant="ghost" onClick={() => uploadBatch.reset()}>
            <X data-icon="inline-start" className="h-4 w-4" />
            Cerrar
          </Button>
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="overflow-hidden">
          <CardHeader className="flex-row items-center justify-between gap-3 border-b">
            <div>
              <CardTitle>Listado</CardTitle>
              <p className="mt-1 text-xs text-[var(--text-muted)]">{total} documentos encontrados</p>
            </div>
            <div className="flex items-center gap-2">
              {selected.length ? <Badge variant="info">{selected.length} seleccionados</Badge> : null}
              <Button
                variant="outline"
                size="sm"
                disabled={!selected.length || bulkReprocess.isPending}
                onClick={() => bulkReprocess.mutate({ ids: selected, mode: "classification" })}
              >
                <RefreshCcw data-icon="inline-start" />
                Reprocesar
              </Button>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10">
                      <input type="checkbox" aria-label="Seleccionar página" checked={rows.length > 0 && rows.every((document) => selectedSet.has(document.id))} onChange={togglePage} />
                    </TableHead>
                    <TableHead>Archivo</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead>Calidad</TableHead>
                    <TableHead>Conf.</TableHead>
                    <TableHead>Tamaño</TableHead>
                    <TableHead>Fecha</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((document) => (
                    <DocumentRow key={document.id} document={document} selected={selectedSet.has(document.id)} onToggle={() => toggleSelected(document.id)} onReprocess={() => reprocess.mutate(document.id)} />
                  ))}
                  {!rows.length ? (
                    <TableRow>
                      <TableCell colSpan={9} className="p-0">
                        <EmptyState
                          title="Sin documentos"
                          description="Ajusta los filtros, sube archivos o lanza el escaneo de carpetas para empezar."
                          action="Escanear carpetas"
                          onAction={() => scan.mutate()}
                          icon={<EmptyDocumentsIllustration />}
                        />
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </div>
            <div className="flex items-center justify-between border-t bg-[var(--bg-surface-2)] px-4 py-3 text-sm">
              <span className="text-muted-foreground">
                Mostrando {rows.length ? offset + 1 : 0}-{offset + rows.length} de {total}
              </span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={offset === 0 || documents.isFetching} onClick={() => setOffset(Math.max(0, offset - pageSize))}>
                  Anterior
                </Button>
                <Button variant="outline" size="sm" disabled={offset + pageSize >= total || documents.isFetching} onClick={() => setOffset(offset + pageSize)}>
                  Siguiente
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Vista activa</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p className="text-muted-foreground">{documentViews.find((item) => item.id === view)?.description}</p>
            <Info label="Filtro texto" value={query || "-"} />
            <Info label="Estado" value={status || params.status || "-"} />
            <Info label="Tipo" value={documentType || params.document_type || "-"} />
            <Info label="Página" value={`${Math.floor(offset / pageSize) + 1}`} />
            {bulkReprocess.data ? (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-emerald-900">
                Encontrados: {bulkReprocess.data.matched}. Encolados: {bulkReprocess.data.enqueued}.
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function DocumentRow({ document, selected, onToggle, onReprocess }: { document: Document; selected: boolean; onToggle: () => void; onReprocess: () => void }) {
  return (
    <TableRow className={selected ? "bg-cyan-50/60" : undefined}>
      <TableCell>
        <input type="checkbox" aria-label={`Seleccionar ${document.original_filename}`} checked={selected} onChange={onToggle} />
      </TableCell>
      <TableCell className="min-w-[260px]">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="h-4 w-4 text-muted-foreground" />
          <div className="min-w-0">
            <p className="truncate font-medium">{document.original_filename}</p>
            <p className="truncate text-xs text-muted-foreground">{document.source_path ?? document.file_hash}</p>
          </div>
        </div>
      </TableCell>
      <TableCell>{document.document_type}</TableCell>
      <TableCell><StatusBadge status={document.status} /></TableCell>
      <TableCell><StatusBadge status={document.quality_status ?? "-"} /></TableCell>
      <TableCell>{document.confidence != null ? `${Math.round(document.confidence * 100)}%` : "-"}</TableCell>
      <TableCell>{formatBytes(document.file_size)}</TableCell>
      <TableCell>{formatDate(document.created_at)}</TableCell>
      <TableCell>
        <div className="flex justify-end gap-1">
          <Button asChild variant="ghost" size="icon" title="Ver documento" aria-label={`Ver ${document.original_filename}`}>
            <Link to={`/documents/${document.id}`}>
              <Eye aria-hidden="true" />
            </Link>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            title="Reprocesar"
            aria-label={`Reprocesar ${document.original_filename}`}
            onClick={onReprocess}
          >
            <RefreshCcw aria-hidden="true" />
          </Button>
          <Button asChild variant="ghost" size="icon" title="Descargar" aria-label={`Descargar ${document.original_filename}`}>
            <a href={downloadUrl(document.id)}>
              <Download aria-hidden="true" />
            </a>
          </Button>
        </div>
      </TableCell>
    </TableRow>
  )
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-md border px-3 py-2">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}

function invalidateDocuments(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["documents"] })
  queryClient.invalidateQueries({ queryKey: ["jobs"] })
  queryClient.invalidateQueries({ queryKey: ["operations-overview"] })
}
