/**
 * Reusable CSV export utility. Replaces ad-hoc exporters in invoices/search.
 */

export interface CsvColumn<T> {
  /** Header label. */
  header: string
  /** Accessor: either a key of T or a function that returns the cell value. */
  accessor: keyof T | ((row: T) => string | number | null | undefined)
  /** Optional format function for the cell value. */
  format?: (value: string | number | null | undefined) => string
}

/**
 * Export an array of data as a CSV file download.
 *
 * @param columns - Column definitions with header + accessor
 * @param rows - Data rows
 * @param filename - Download filename (without .csv extension)
 */
export function exportCsv<T>(columns: CsvColumn<T>[], rows: T[], filename: string) {
  const escape = (val: string) => {
    if (val.includes(",") || val.includes('"') || val.includes("\n")) {
      return `"${val.replace(/"/g, '""')}"`
    }
    return val
  }

  const headers = columns.map((col) => escape(col.header))

  const data = rows.map((row) =>
    columns
      .map((col) => {
        const raw =
          typeof col.accessor === "function"
            ? col.accessor(row)
            : (row[col.accessor] as string | number | null | undefined)
        const formatted = col.format ? col.format(raw) : raw
        return escape(String(formatted ?? ""))
      })
      .join(","),
  )

  const csv = [headers.join(","), ...data].join("\n")
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" })
  const url = URL.createObjectURL(blob)

  const link = document.createElement("a")
  link.href = url
  link.download = `${filename}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
