import { ChangeEvent, useCallback, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, CheckCircle2, Download, Eye, FileSpreadsheet, FolderUp, Loader2, RefreshCcw, Search, Upload, X } from "lucide-react"

import { api, downloadUrl } from "@/api/client"
import { AutoBreadcrumbs } from "@/components/layout/AutoBreadcrumbs"
import { EmptyState } from "@/components/layout/EmptyState"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { applyDocumentView, documentViews, type DocumentViewId } from "@/lib/documentViews"
import { cn, formatBytes, formatDate } from "@/lib/utils"
import { notify } from "@/lib/toast"
import type { Document } from "@/types/api"

const PAGE_SIZE = 25
const STATUS_OPTIONS = [
  { value: "", label: "Todos" },
  { value: "pending", label: "Pendiente" },
  { value: "processing", label: "Procesando" },
  { value: "processed", label: "Procesado" },
  { value: "needs_review", label: "Revisión" },
  { value: "failed", label: "Fallido" },
  { value: "duplicate", label: "Duplicado" },
]
const TYPE_OPTIONS = [
  { value: "", label: "Todos" },
  { value: "presupuesto", label: "Presupuesto" },
  { value: "pedido", label: "Pedido" },
  { value: "factura", label: "Factura" },
  { value: "plano", label: "Plano" },
  { value: "imagen", label: "Imagen" },
  { value: "excel", label: "Excel" },
  { value: "otro", label: "Otro" },
]

export function DocumentsPage() {
  const qc = useQueryClient()
  const [view, setView] = useState<DocumentViewId>("all")
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState("")
  const [docType, setDocType] = useState("")
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<number[]>([])
  const [dragging, setDragging] = useState(false)

  const params = useMemo(() => {
    const vf = applyDocumentView(view, { q: query, limit: PAGE_SIZE, offset })
    return { ...vf, status: status || vf.status, document_type: docType || vf.document_type }
  }, [docType, offset, query, status, view])

  const docs = useQuery({ queryKey: ["documents", "ops", params], queryFn: () => api.operationsDocuments(params) })
  const rows = docs.data?.items ?? []
  const total = docs.data?.total ?? 0
  const selSet = useMemo(() => new Set(selected), [selected])

  const upload = useMutation({
    mutationFn: api.upload,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["documents"] }); notify.success("Subido", "Encolado para procesamiento.") },
    onError: (e) => notify.error(e, "Error al subir"),
  })
  const uploadBatch = useMutation({
    mutationFn: (p: { files: File[]; relativePaths?: string[] }) => api.uploadBatch(p.files, p.relativePaths),
    onSuccess: (d) => { qc.invalidateQueries({ queryKey: ["documents"] }); notify.success("Subida completada", `${d.uploaded} nuevos, ${d.duplicates} duplicados, ${d.failed} fallidos.`) },
    onError: (e) => notify.error(e, "Error al subir"),
  })
  const scan = useMutation({
    mutationFn: api.scan,
    onSuccess: (d) => { qc.invalidateQueries({ queryKey: ["documents"] }); notify.success("Escaneo", `${d.registered} nuevos, ${d.duplicates} duplicados.`) },
    onError: (e) => notify.error(e, "Error al escanear"),
  })
  const reprocess = useMutation({
    mutationFn: api.reprocess,
    onSuccess: (j) => { qc.invalidateQueries({ queryKey: ["documents"] }); notify.success("Reprocesado", `Job #${j.id}`) },
    onError: (e) => notify.error(e, "Error"),
  })
  const bulkReprocess = useMutation({
    mutationFn: api.reprocessBulk,
    onSuccess: (d) => { setSelected([]); qc.invalidateQueries({ queryKey: ["documents"] }); notify.success("Lote", `${d.enqueued} encolados`) },
    onError: (e) => notify.error(e, "Error"),
  })

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length) uploadBatch.mutate({ files })
  }, [uploadBatch])

  function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (files?.length) {
      if (files.length === 1) upload.mutate(files[0])
      else uploadBatch.mutate({ files: Array.from(files) })
    }
    e.target.value = ""
  }

  function onFolderChange(e: ChangeEvent<HTMLInputElement>) {
    const files = e.target.files
    if (files?.length) {
      const arr = Array.from(files)
      uploadBatch.mutate({ files: arr, relativePaths: arr.map((f) => (f as File & { webkitRelativePath?: string }).webkitRelativePath ?? f.name) })
    }
    e.target.value = ""
  }

  function changeView(v: DocumentViewId) { setView(v); setStatus(""); setDocType(""); setOffset(0); setSelected([]) }
  function toggleSel(id: number) { setSelected((c) => c.includes(id) ? c.filter((i) => i !== id) : [...c, id]) }
  function togglePage() { const ids = rows.map((d) => d.id); const all = ids.length > 0 && ids.every((id) => selSet.has(id)); setSelected((c) => all ? c.filter((id) => !ids.includes(id)) : Array.from(new Set([...c, ...ids]))) }

  return (
    <div className="space-y-4" onDragOver={(e) => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
      <AutoBreadcrumbs />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-[18px] font-semibold text-[var(--text-primary)]">Documentos</h1>
          <p className="text-[12px] text-[var(--text-muted)]">{total} documentos · Filtros de servidor, vistas guardadas y acciones masivas.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => scan.mutate()} disabled={scan.isPending}><RefreshCcw className="mr-1 h-3 w-3" /> Escanear</Button>
          <Button size="sm" asChild><label className="cursor-pointer"><Upload className="mr-1 h-3 w-3" /> Subir<input className="hidden" type="file" multiple onChange={onFileChange} /></label></Button>
          <Button variant="outline" size="sm" asChild><label className="cursor-pointer"><FolderUp className="mr-1 h-3 w-3" /> Carpeta<input {...{ className: "hidden", type: "file", webkitdirectory: "", directory: "", multiple: true, onChange: onFolderChange } as React.InputHTMLAttributes<HTMLInputElement>} /></label></Button>
        </div>
      </div>

      {dragging && <div className="flex items-center justify-center rounded-lg border-2 border-dashed border-[var(--accent)] bg-[var(--accent-light)] py-6"><Upload className="mr-2 h-5 w-5 text-[var(--accent)]" /><span className="text-[13px] font-medium text-[var(--accent)]">Suelta archivos</span></div>}

      {(upload.isPending || uploadBatch.isPending) && <Banner tone="info"><Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" /> Subiendo...</Banner>}
      {(upload.isError || uploadBatch.isError) && <Banner tone="danger" onDismiss={() => { upload.reset(); uploadBatch.reset() }}>Error: {upload.error?.message ?? uploadBatch.error?.message}</Banner>}
      {upload.isSuccess && <Banner tone="success" onDismiss={() => upload.reset()}>Archivo subido.</Banner>}
      {uploadBatch.isSuccess && uploadBatch.data && <Banner tone="success" onDismiss={() => uploadBatch.reset()}>Subidos: {uploadBatch.data.uploaded} nuevos, {uploadBatch.data.duplicates} dup, {uploadBatch.data.failed} fallos.</Banner>}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-0.5 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-0.5">
          {documentViews.map((v) => (
            <button key={v.id} type="button" onClick={() => changeView(v.id)} className={cn("rounded px-2.5 py-1 text-[11px] font-medium transition-colors", v.id === view ? "bg-[var(--bg-surface-2)] text-[var(--text-primary)] shadow-xs" : "text-[var(--text-muted)] hover:text-[var(--text-primary)]")}>{v.label}</button>
          ))}
        </div>
        <div className="relative flex-1 min-w-[160px] max-w-[240px]">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
          <Input className="h-8 pl-7 text-[12px]" value={query} onChange={(e) => { setQuery(e.target.value); setOffset(0) }} placeholder="Buscar..." />
        </div>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }} className="h-8 rounded-md border border-[var(--border-2)] bg-[var(--bg-surface)] px-2 text-[12px] text-[var(--text-primary)]">
          {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select value={docType} onChange={(e) => { setDocType(e.target.value); setOffset(0) }} className="h-8 rounded-md border border-[var(--border-2)] bg-[var(--bg-surface)] px-2 text-[12px] text-[var(--text-primary)]">
          {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8"><input type="checkbox" aria-label="Todo" checked={rows.length > 0 && rows.every((d) => selSet.has(d.id))} onChange={togglePage} /></TableHead>
                <TableHead>Archivo</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead className="text-right">OCR</TableHead>
                <TableHead>Tamaño · Fecha</TableHead>
                <TableHead className="text-right">Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((doc) => (
                <TableRow key={doc.id} className={cn(selected.includes(doc.id) && "bg-[var(--accent-faint)]")}>
                  <TableCell><input type="checkbox" checked={selSet.has(doc.id)} onChange={() => toggleSel(doc.id)} aria-label={doc.original_filename} /></TableCell>
                  <TableCell>
                    <Link to={`/documents/${doc.id}`} className="truncate text-[12px] font-medium text-[var(--text-primary)] hover:underline">{doc.original_filename}</Link>
                    <p className="truncate text-[10px] text-[var(--text-muted)]">{doc.source_path ?? doc.file_hash?.slice(0, 16)}</p>
                  </TableCell>
                  <TableCell><div className="flex flex-col gap-0.5"><StatusBadge status={doc.status} /><StatusBadge status={doc.quality_status ?? "-"} /></div></TableCell>
                  <TableCell className="text-[11px] text-[var(--text-muted)]">{doc.document_type}</TableCell>
                  <TableCell className="text-right text-[12px] tabular-nums">{doc.confidence != null ? `${Math.round(doc.confidence * 100)}%` : "—"}</TableCell>
                  <TableCell className="text-[11px] text-[var(--text-muted)]"><span className="font-medium text-[var(--text-secondary)]">{formatBytes(doc.file_size)}</span> · {formatDate(doc.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-0.5">
                      <Button asChild variant="ghost" size="icon" className="h-7 w-7"><Link to={`/documents/${doc.id}`}><Eye className="h-3.5 w-3.5" /></Link></Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => reprocess.mutate(doc.id)}><RefreshCcw className="h-3.5 w-3.5" /></Button>
                      <Button asChild variant="ghost" size="icon" className="h-7 w-7"><a href={downloadUrl(doc.id)}><Download className="h-3.5 w-3.5" /></a></Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
              {!rows.length && <TableRow><TableCell colSpan={7}><EmptyState title="Sin documentos" description="Sube archivos o escanea carpetas." /></TableCell></TableRow>}
            </TableBody>
          </Table>
          <div className="flex items-center justify-between border-t border-[var(--border)] px-4 py-2 text-[11px]">
            <span className="text-[var(--text-muted)]">{rows.length ? offset + 1 : 0}–{offset + rows.length} de {total}</span>
            <div className="flex gap-1">
              {selected.length > 0 && <>
                <Badge variant="info" className="text-[10px]">{selected.length} sel.</Badge>
                <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={() => setSelected([])}>Limpiar</Button>
                <Button variant="outline" size="sm" className="h-6 text-[10px]" disabled={bulkReprocess.isPending} onClick={() => bulkReprocess.mutate({ ids: selected, mode: "classification" })}>Reprocesar</Button>
              </>}
              <Button variant="outline" size="sm" className="h-6 text-[10px]" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Ant.</Button>
              <Button variant="outline" size="sm" className="h-6 text-[10px]" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>Sig.</Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function Link({ to, className, children, ...props }: { to: string; className?: string; children: React.ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <a href={to} className={className} {...props}>{children}</a>
}

function Banner({ tone, children, onDismiss }: { tone: "info" | "danger" | "success"; children: React.ReactNode; onDismiss?: () => void }) {
  const c = { info: "border-[var(--info)]/20 bg-[var(--info-faint)] text-[var(--text-on-info)]", danger: "border-[var(--danger)]/20 bg-[var(--danger-faint)] text-[var(--text-on-danger)]", success: "border-[var(--success)]/20 bg-[var(--success-faint)] text-[var(--text-on-success)]" }
  return <div className={cn("flex items-center justify-between rounded-md border px-3 py-2 text-[12px]", c[tone])}><span>{children}</span>{onDismiss && <button onClick={onDismiss} className="ml-2 opacity-60 hover:opacity-100"><X className="h-3 w-3" /></button>}</div>
}
