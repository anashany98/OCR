import { ChangeEvent, useMemo, useState, useCallback } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { Download, Eye, FileSpreadsheet, RefreshCcw, Search, Upload } from "lucide-react"

import { api, downloadUrl } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatBytes, formatDate } from "@/lib/utils"
import type { Document } from "@/types/api"

export function DocumentsPage() {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState("")
  const [isDragging, setIsDragging] = useState(false)
  const documents = useQuery({ queryKey: ["documents"], queryFn: api.documents })
  const upload = useMutation({
    mutationFn: api.upload,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  })
  const uploadBatch = useMutation({
    mutationFn: api.uploadBatch,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  })
  const scan = useMutation({
    mutationFn: api.scan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents"] })
      queryClient.invalidateQueries({ queryKey: ["jobs"] })
    },
  })
  const reprocess = useMutation({
    mutationFn: api.reprocess,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents"] }),
  })

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      const files = Array.from(e.dataTransfer.files)
      if (files.length > 0) {
        uploadBatch.mutate(files)
      }
    },
    [uploadBatch],
  )

  const columns = useMemo<ColumnDef<Document>[]>(
    () => [
      {
        header: "Archivo",
        accessorKey: "original_filename",
        cell: ({ row }) => <span className="font-medium">{row.original.original_filename}</span>,
      },
      { header: "Tipo", accessorKey: "document_type" },
      {
        header: "Estado",
        accessorKey: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        header: "Conf.",
        accessorKey: "confidence",
        cell: ({ row }) => (row.original.confidence != null ? `${Math.round(row.original.confidence * 100)}%` : "-"),
      },
      { header: "Tamano", accessorFn: (row) => formatBytes(row.file_size) },
      { header: "Fecha", accessorFn: (row) => formatDate(row.created_at) },
      {
        header: "",
        id: "actions",
        cell: ({ row }) => (
          <div className="flex justify-end gap-1">
            <Button asChild variant="ghost" size="icon" title="Ver">
              <Link to={`/documents/${row.original.id}`}>
                <Eye />
              </Link>
            </Button>
            <Button variant="ghost" size="icon" title="Reprocesar" onClick={() => reprocess.mutate(row.original.id)}>
              <RefreshCcw />
            </Button>
            <Button asChild variant="ghost" size="icon" title="Descargar">
              <a href={downloadUrl(row.original.id)}>
                <Download />
              </a>
            </Button>
          </div>
        ),
      },
    ],
    [reprocess],
  )

  const table = useReactTable({
    data: documents.data ?? [],
    columns,
    state: { globalFilter: filter },
    onGlobalFilterChange: setFilter,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  })

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files
    if (files && files.length > 0) {
      if (files.length === 1) {
        upload.mutate(files[0])
      } else {
        uploadBatch.mutate(Array.from(files))
      }
    }
    event.target.value = ""
  }

  return (
    <div
      className="flex flex-col gap-4"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
        <PageHeader title="Documentos" description="Subida, escaneo, reprocesado y acceso a originales protegidos." />
        <div className="flex flex-wrap gap-2">
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
        </div>
      </div>

      {isDragging && (
        <div className="flex items-center justify-center py-8 border-2 border-dashed border-primary rounded-lg bg-primary/5">
          <div className="flex flex-col items-center gap-2 text-primary">
            <Upload className="h-8 w-8" />
            <span className="font-medium">Suelta archivos para subir</span>
          </div>
        </div>
      )}

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3">
          <CardTitle>Listado</CardTitle>
          <div className="flex w-full max-w-sm items-center gap-2">
            <Search className="text-muted-foreground" />
            <Input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filtrar tabla" />
          </div>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHead key={header.id}>
                      {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  ))}
                </TableRow>
              ))}
              {!table.getRowModel().rows.length ? (
                <TableRow>
                  <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">
                    Sin documentos.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
