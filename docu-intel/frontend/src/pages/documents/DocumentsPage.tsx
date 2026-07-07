/**
 * F8 - Documents operations page.
 *
 * F8b - Layout:
 *   - Removed the right-hand "Vista activa" sidebar card (it duplicated
 *     the toolbar filter state and added visual noise).
 *   - Reduced the table from 9 columns to 7 by combining
 *     Estado+Calidad and Tamano+Fecha into single cells.
 *   - Styled native selects to match the OCR review filters.
 *   - View filters as outlined tabs (not pills) for clearer state.
 */
import { ChangeEvent, useCallback, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertCircle,
  CheckCircle2,
  Download,
  Eye,
  FileSpreadsheet,
  FolderUp,
  Loader2,
  RefreshCcw,
  Search,
  Upload,
  X,
} from "lucide-react"

import { api, downloadUrl } from "@/api/client"
import { EmptyState } from "@/components/layout/EmptyState"
import { PageHeader } from "@/components/layout/PageHeader"
import { PageToolbar } from "@/components/layout/PageToolbar"
import { StatusBadge } from "@/components/layout/StatusBadge"
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
import { applyDocumentView, documentViews, type DocumentViewId } from "@/lib/documentViews"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { EmptyDocumentsIllustration } from "@/components/illustrations/EditorialIllustrations"
import { notify } from "@/lib/toast"
import { cn, formatBytes, formatDate } from "@/lib/utils"
import type { Document } from "@/types/api"

import { DocumentRow } from "./DocumentRow"

const pageSize = 25
const statusOptions = [
  { value: "", label: "Todos los estados" },
  { value: "pending", label: "Pendiente" },
  { value: "processing", label: "Procesando" },
  { value: "processed", label: "Procesado" },
  { value: "needs_review", label: "Necesita revisión" },
  { value: "failed", label: "Fallido" },
  { value: "duplicate", label: "Duplicado" },
]
const typeOptions = [
  { value: "", label: "Todos los tipos" },
  { value: "presupuesto", label: "Presupuesto" },
  { value: "pedido", label: "Pedido" },
  { value: "factura", label: "Factura" },
  { value: "plano", label: "Plano" },
  { value: "imagen", label: "Imagen" },
  { value: "excel", label: "Excel" },
  { value: "otro", label: "Otro" },
]

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

  const documents = useQuery({
    queryKey: ["documents", "operations", params],
    queryFn: () => api.operationsDocuments(params),
  })
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
    setSelected((current) =>
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId],
    )
  }

  function togglePage() {
    const rowIds = rows.map((document) => document.id)
    const allSelected = rowIds.length > 0 && rowIds.every((id) => selectedSet.has(id))
    setSelected((current) =>
      allSelected
        ? current.filter((id) => !rowIds.includes(id))
        : Array.from(new Set([...current, ...rowIds])),
    )
  }

  function clearSelection() {
    setSelected([])
  }

  return (
    <div
      className="flex flex-col gap-6"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
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
                  /* eslint-disable-next-line react/no-unknown-property -- HTML5 dir-upload attribute */
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
        <div className="flex items-center justify-center rounded-lg border-2 border-dashed border-primary bg-primary/5 py-8">
          <div className="flex flex-col items-center gap-2 text-primary">
            <Upload className="h-8 w-8" />
            <span className="font-medium">Suelta archivos para subir</span>
          </div>
        </div>
      ) : null}

      <PageToolbar>
        {/* View tabs */}
        <div className="flex flex-wrap items-center gap-1 rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-1">
          {documentViews.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => changeView(item.id)}
              className={cn(
                "rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors",
                item.id === view
                  ? "bg-[var(--bg-surface-2)] text-[var(--text-primary)] shadow-xs"
                  : "text-[var(--text-muted)] hover:text-[var(--text-primary)]",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>

        {/* Search + filters */}
        <div className="relative min-w-[220px] flex-1 md:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-[var(--text-muted)]" />
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
        <StyledSelect
          aria-label="Estado"
          value={status}
          onChange={(value) => {
            setStatus(value)
            setOffset(0)
          }}
          options={statusOptions}
        />
        <StyledSelect
          aria-label="Tipo"
          value={documentType}
          onChange={(value) => {
            setDocumentType(value)
            setOffset(0)
          }}
          options={typeOptions}
        />
      </PageToolbar>

      {upload.isPending || uploadBatch.isPending ? (
        <StatusBanner tone="info" icon={<Loader2 className="h-4 w-4 animate-spin" />}>
          {upload.isPending
            ? "Subiendo archivo..."
            : `Subiendo ${uploadBatch.variables?.files?.length ?? "varios"} archivo(s)...`}
        </StatusBanner>
      ) : null}

      {upload.isError || uploadBatch.isError ? (
        <StatusBanner
          tone="danger"
          icon={<AlertCircle className="h-4 w-4 shrink-0" />}
          action={
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
          }
        >
          Error al subir:{" "}
          {upload.error?.message ?? uploadBatch.error?.message ?? "fallo desconocido"}
        </StatusBanner>
      ) : null}

      {upload.isSuccess ? (
        <StatusBanner
          tone="success"
          icon={<CheckCircle2 className="h-4 w-4 shrink-0" />}
          action={
            <Button size="sm" variant="ghost" onClick={() => upload.reset()}>
              <X data-icon="inline-start" className="h-4 w-4" />
              Cerrar
            </Button>
          }
        >
          Archivo subido correctamente.
        </StatusBanner>
      ) : null}

      {uploadBatch.isSuccess && uploadBatch.data ? (
        <StatusBanner
          tone="success"
          icon={<CheckCircle2 className="h-4 w-4 shrink-0" />}
          action={
            <Button size="sm" variant="ghost" onClick={() => uploadBatch.reset()}>
              <X data-icon="inline-start" className="h-4 w-4" />
              Cerrar
            </Button>
          }
        >
          Subida completada: {uploadBatch.data.uploaded} nuevo(s), {uploadBatch.data.duplicates}{" "}
          duplicado(s), {uploadBatch.data.failed} fallido(s).
        </StatusBanner>
      ) : null}

      <Card className="overflow-hidden">
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0 border-b bg-muted/20 px-5 py-3">
          <div className="flex items-center gap-3">
            <CardTitle className="text-sm font-semibold">Listado</CardTitle>
            <span className="text-xs text-[var(--text-muted)] tabular-nums">{total} documentos</span>
          </div>
          <div className="flex items-center gap-2">
            {selected.length > 0 ? (
              <Badge variant="info" className="tabular-nums">
                {selected.length} seleccionados
              </Badge>
            ) : null}
            {selected.length > 0 ? (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearSelection}
                  disabled={bulkReprocess.isPending}
                >
                  <X data-icon="inline-start" className="h-3.5 w-3.5" />
                  Limpiar
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={bulkReprocess.isPending}
                  onClick={() => bulkReprocess.mutate({ ids: selected, mode: "classification" })}
                >
                  <RefreshCcw data-icon="inline-start" />
                  Reprocesar selección
                </Button>
              </>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => documents.refetch()}
                disabled={documents.isFetching}
              >
                <RefreshCcw
                  data-icon={documents.isFetching ? undefined : "inline-start"}
                  className={cn(documents.isFetching && "animate-spin")}
                />
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">
                  <input
                    type="checkbox"
                    aria-label="Seleccionar página"
                    checked={
                      rows.length > 0 && rows.every((document) => selectedSet.has(document.id))
                    }
                    onChange={togglePage}
                  />
                </TableHead>
                <TableHead>Archivo</TableHead>
                <TableHead className="w-[260px]">Estado · Calidad</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead className="w-[100px] text-right">Confianza</TableHead>
                <TableHead className="w-[160px]">Tamaño · Fecha</TableHead>
                <TableHead className="w-[120px] text-right">Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((document) => (
                <DocumentRow
                  key={document.id}
                  document={document}
                  selected={selectedSet.has(document.id)}
                  onToggle={() => toggleSelected(document.id)}
                  onReprocess={() => reprocess.mutate(document.id)}
                />
              ))}
              {!rows.length ? (
                <TableRow>
                  <TableCell colSpan={7} className="p-0">
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
          <div className="flex items-center justify-between border-t bg-[var(--bg-surface-2)] px-5 py-3 text-sm">
            <span className="text-[var(--text-muted)] tabular-nums">
              Mostrando {rows.length ? offset + 1 : 0}–{offset + rows.length} de {total}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={offset === 0 || documents.isFetching}
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
              >
                Anterior
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={offset + pageSize >= total || documents.isFetching}
                onClick={() => setOffset(offset + pageSize)}
              >
                Siguiente
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Local primitives
// ---------------------------------------------------------------------------

function StyledSelect<T extends string>({
  value,
  onChange,
  options,
  ...rest
}: {
  value: T
  onChange: (next: T) => void
  options: { value: T; label: string }[]
} & Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange" | "children">) {
  return (
    <select
      {...rest}
      value={value}
      onChange={(e) => onChange(e.target.value as T)}
      className="h-9 rounded-md border border-input bg-[var(--bg-canvas)] px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
    >
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  )
}

function StatusBanner({
  tone,
  icon,
  children,
  action,
}: {
  tone: "info" | "danger" | "success"
  icon: React.ReactNode
  children: React.ReactNode
  action?: React.ReactNode
}) {
  const toneClasses = {
    info: "border-[var(--info)]/20 bg-[var(--info-faint)] text-[var(--text-on-info)]",
    danger: "border-[var(--danger)]/20 bg-[var(--danger-faint)] text-[var(--text-on-danger)]",
    success: "border-[var(--positive)]/20 bg-[var(--positive-faint)] text-[var(--text-on-success)]",
  }
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-2 rounded-md border px-4 py-3 text-sm",
        toneClasses[tone],
      )}
      role={tone === "danger" ? "alert" : "status"}
      aria-live={tone === "danger" ? "assertive" : "polite"}
    >
      <div className="flex min-w-0 items-center gap-2">
        {icon}
        <span className="truncate">{children}</span>
      </div>
      {action}
    </div>
  )
}

function invalidateDocuments(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["documents"] })
  queryClient.invalidateQueries({ queryKey: ["jobs"] })
  queryClient.invalidateQueries({ queryKey: ["operations-overview"] })
}
