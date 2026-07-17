import { useEffect, useState } from "react"
import {
  type ColumnDef,
  type ColumnFiltersState,
  type SortingState,
  type VisibilityState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import { useTableState } from "@/lib/useTableState"
import { cn } from "@/lib/utils"

export interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
  /** Unique ID for state persistence. */
  tableId?: string
  /** Enable client-side pagination. For server-side, handle externally. */
  pagination?: boolean
  /** Page size for client-side pagination. */
  pageSize?: number
  /** Row click handler. */
  onRowClick?: (row: TData) => void
  /** Enable row selection checkboxes. */
  selectable?: boolean
  /** Selection change handler. */
  onSelectionChange?: (selected: TData[]) => void
  /** Density mode. */
  density?: "comfortable" | "compact"
  /** Empty state content. */
  emptyContent?: React.ReactNode
  /** Loading state. */
  loading?: boolean
  /** Additional class names for the root element. */
  className?: string
}

export function DataTable<TData, TValue>({
  columns,
  data,
  tableId,
  pagination = true,
  pageSize = 25,
  onRowClick,
  selectable = false,
  onSelectionChange,
  density = "comfortable",
  emptyContent,
  loading = false,
  className,
}: DataTableProps<TData, TValue>) {
  const saved = useTableState(tableId ?? "default")
  const [sorting, setSorting] = useState<SortingState>(saved.sort ? [saved.sort] : [])
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    saved.columnVisibility ?? {},
  )
  const [rowSelection, setRowSelection] = useState({})
  const [pageIndex, setPageIndex] = useState(saved.pagination?.pageIndex ?? 0)

  const allColumns: ColumnDef<TData, TValue>[] = selectable
    ? [
        {
          id: "select",
          header: ({ table }) => (
            <Checkbox
              checked={
                table.getIsAllPageRowsSelected() ||
                (table.getIsSomePageRowsSelected() && "indeterminate")
              }
              onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
              aria-label="Seleccionar todo"
              className="translate-y-[2px]"
            />
          ),
          cell: ({ row }) => (
            <Checkbox
              checked={row.getIsSelected()}
              onCheckedChange={(value) => row.toggleSelected(!!value)}
              aria-label="Seleccionar fila"
              className="translate-y-[2px]"
            />
          ),
          enableSorting: false,
          enableHiding: false,
          size: 40,
        } as ColumnDef<TData, TValue>,
        ...columns,
      ]
    : columns

  const table = useReactTable({
    data,
    columns: allColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: pagination ? getPaginationRowModel() : undefined,
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onSortingChange: (updater) => {
      const next = typeof updater === "function" ? updater(sorting) : updater
      setSorting(next)
      saved.setSort(next[0])
    },
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    pageCount: pagination ? Math.ceil(data.length / pageSize) : undefined,
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      rowSelection,
      pagination: pagination ? { pageIndex, pageSize } : undefined,
    },
    onPaginationChange: (updater) => {
      if (typeof updater === "function") {
        const next = updater({ pageIndex, pageSize })
        setPageIndex(next.pageIndex)
        saved.setPagination({ pageIndex: next.pageIndex, pageSize })
      }
    },
    enableRowSelection: selectable,
  })

  // Notify parent of selection changes
  useEffect(() => {
    if (selectable && onSelectionChange) {
      const selectedRows = table.getFilteredSelectedRowModel().rows.map((r) => r.original)
      onSelectionChange(selectedRows)
    }
    // Only react to rowSelection changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rowSelection])

  const isCompact = density === "compact"

  if (loading) {
    return (
      <div
        className={cn("rounded-xl border border-[var(--border)] bg-[var(--bg-surface)]", className)}
      >
        <div className="p-4 space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className={cn("w-full", isCompact ? "h-8" : "h-12")} />
          ))}
        </div>
      </div>
    )
  }

  const tableRows = table.getRowModel().rows

  return (
    <div
      className={cn("rounded-xl border border-[var(--border)] bg-[var(--bg-surface)]", className)}
    >
      <div className="overflow-x-auto">
        <table className="w-full caption-bottom text-[13px]">
          <thead className="border-b border-[var(--border)]">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className={cn(
                      "h-10 px-3 text-left font-medium text-[var(--text-muted)]",
                      header.column.getCanSort() &&
                        "cursor-pointer select-none hover:text-[var(--text-primary)]",
                      isCompact && "h-8",
                    )}
                    style={{
                      width: header.column.getSize() !== 150 ? header.column.getSize() : undefined,
                    }}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    <div className="flex items-center gap-1">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() === "asc" && " ↑"}
                      {header.column.getIsSorted() === "desc" && " ↓"}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {tableRows.length === 0 ? (
              <tr>
                <td
                  colSpan={allColumns.length}
                  className="h-24 text-center text-[var(--text-muted)]"
                >
                  {emptyContent ?? "Sin resultados"}
                </td>
              </tr>
            ) : (
              tableRows.map((row) => (
                <tr
                  key={row.id}
                  data-state={row.getIsSelected() && "selected"}
                  className={cn(
                    "border-b border-[var(--border)] transition-colors",
                    "hover:bg-[var(--bg-surface-2)]/50",
                    "data-[state=selected]:bg-[var(--accent-light)]",
                    onRowClick && "cursor-pointer",
                    isCompact && "h-9",
                  )}
                  onClick={() => onRowClick?.(row.original)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className={cn("px-3 py-2 text-[var(--text-primary)]", isCompact && "py-1")}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination footer */}
      {pagination && data.length > pageSize && (
        <div className="flex items-center justify-between border-t border-[var(--border)] px-3 py-2">
          <p className="text-[12px] text-[var(--text-muted)]">
            {table.getFilteredSelectedRowModel().rows.length} de {data.length} fila(s)
          </p>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon"
              className="h-7 w-7"
              onClick={() => table.setPageIndex(0)}
              disabled={!table.getCanPreviousPage()}
            >
              <ChevronsLeft className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-7 w-7"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <span className="px-2 text-[12px] text-[var(--text-muted)]">
              {table.getState().pagination.pageIndex + 1} / {table.getPageCount()}
            </span>
            <Button
              variant="outline"
              size="icon"
              className="h-7 w-7"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              className="h-7 w-7"
              onClick={() => table.setPageIndex(table.getPageCount() - 1)}
              disabled={!table.getCanNextPage()}
            >
              <ChevronsRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
