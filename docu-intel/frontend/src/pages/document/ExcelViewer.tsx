import { useMemo, useState } from "react"
import { ChevronDown, ChevronUp, Search } from "lucide-react"

interface SheetData {
  name: string
  headers: string[]
  rows: string[][]
}

function parseMarkdownTable(text: string): SheetData[] {
  const sheets: SheetData[] = []
  const sections = text.split(/^### /m).filter(Boolean)

  for (const section of sections) {
    const lines = section.trim().split("\n")
    const name = lines[0]?.replace(/^Hoja:\s*/, "").trim() || "Hoja"
    const tableLines = lines.filter((l) => l.startsWith("|"))

    if (tableLines.length < 2) {
      sheets.push({ name, headers: [], rows: [] })
      continue
    }

    const parseRow = (line: string) =>
      line
        .split("|")
        .slice(1, -1)
        .map((c) => c.trim())

    const headers = parseRow(tableLines[0])
    const rows = tableLines.slice(2).map(parseRow)

    sheets.push({ name, headers, rows })
  }

  if (sheets.length === 0 && text.includes("|")) {
    const lines = text.split("\n").filter((l) => l.startsWith("|"))
    if (lines.length >= 2) {
      const parseRow = (line: string) =>
        line
          .split("|")
          .slice(1, -1)
          .map((c) => c.trim())
      const headers = parseRow(lines[0])
      const rows = lines.slice(2).map(parseRow)
      sheets.push({ name: "Datos", headers, rows })
    }
  }

  return sheets
}

export function ExcelViewer({ text }: { text: string }) {
  const sheets = useMemo(() => parseMarkdownTable(text), [text])
  const [activeSheet, setActiveSheet] = useState(0)
  const [search, setSearch] = useState("")
  const [sortCol, setSortCol] = useState<number | null>(null)
  const [sortAsc, setSortAsc] = useState(true)

  const sheet = sheets[activeSheet]
  if (!sheet || sheet.rows.length === 0) {
    return (
      <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
        Sin datos para mostrar
      </div>
    )
  }

  const filteredRows = sheet.rows.filter((row) => {
    if (!search) return true
    const q = search.toLowerCase()
    return row.some((cell) => cell.toLowerCase().includes(q))
  })

  const sortedRows = useMemo(() => {
    if (sortCol === null) return filteredRows
    return [...filteredRows].sort((a, b) => {
      const av = a[sortCol] || ""
      const bv = b[sortCol] || ""
      const an = parseFloat(av.replace(/[.,]/g, ""))
      const bn = parseFloat(bv.replace(/[.,]/g, ""))
      if (!isNaN(an) && !isNaN(bn)) return sortAsc ? an - bn : bn - an
      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av)
    })
  }, [filteredRows, sortCol, sortAsc])

  const toggleSort = (col: number) => {
    if (sortCol === col) {
      setSortAsc(!sortAsc)
    } else {
      setSortCol(col)
      setSortAsc(true)
    }
  }

  return (
    <div className="flex flex-col">
      {sheets.length > 1 && (
        <div className="flex gap-1 border-b px-3 pt-2">
          {sheets.map((s, i) => (
            <button
              key={i}
              className={`rounded-t-md px-3 py-1.5 text-xs font-medium transition-colors ${
                i === activeSheet
                  ? "bg-white text-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-white/50"
              }`}
              onClick={() => {
                setActiveSheet(i)
                setSearch("")
                setSortCol(null)
              }}
            >
              {s.name}
              <span className="ml-1 text-[10px] text-muted-foreground">({s.rows.length})</span>
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 border-b px-3 py-2">
        <Search className="h-3.5 w-3.5 text-muted-foreground" />
        <input
          className="flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
          placeholder="Filtrar filas..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <span className="text-[10px] text-muted-foreground">
            {sortedRows.length}/{sheet.rows.length}
          </span>
        )}
      </div>

      <div className="overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-slate-50">
            <tr>
              <th className="w-8 border-b px-2 py-1.5 text-left text-muted-foreground">#</th>
              {sheet.headers.map((h, i) => (
                <th
                  key={i}
                  className="cursor-pointer whitespace-nowrap border-b px-2 py-1.5 text-left font-medium text-foreground hover:bg-slate-100"
                  onClick={() => toggleSort(i)}
                >
                  <span className="inline-flex items-center gap-1">
                    {h}
                    {sortCol === i &&
                      (sortAsc ? (
                        <ChevronUp className="h-3 w-3" />
                      ) : (
                        <ChevronDown className="h-3 w-3" />
                      ))}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((row, ri) => (
              <tr key={ri} className="hover:bg-slate-50/50">
                <td className="border-b px-2 py-1 text-muted-foreground">{ri + 1}</td>
                {row.map((cell, ci) => (
                  <td key={ci} className="border-b px-2 py-1">
                    {cell || <span className="text-muted-foreground">—</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
