import { FormEvent, useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Bookmark, Download, ExternalLink, FileJson, Search, Star } from "lucide-react"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

export function SearchPage() {
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const [query, setQuery] = useState("")
  const [submitted, setSubmitted] = useState("")
  const [mode, setMode] = useState<SearchMode>("hybrid")
  const [savedName, setSavedName] = useState("")

  const savedSearches = useQuery({ queryKey: ["saved-searches"], queryFn: api.savedSearches })
  const results = useQuery({
    queryKey: ["search", mode, submitted],
    queryFn: () => {
      if (mode === "semantic") return api.semanticSearch(submitted)
      if (mode === "hybrid") return api.hybridSearch(submitted)
      if (mode.startsWith("guided:")) return api.guidedSearch(submitted, mode.replace("guided:", ""))
      return api.textSearch(submitted)
    },
    enabled: submitted.length > 0,
  })
  const saveSearch = useMutation({
    mutationFn: () => api.createSavedSearch({ name: savedName.trim() || submitted, query: submitted, mode, filters_json: {} }),
    onSuccess: () => {
      setSavedName("")
      queryClient.invalidateQueries({ queryKey: ["saved-searches"] })
    },
  })

  useEffect(() => {
    const urlQuery = searchParams.get("q")?.trim()
    if (urlQuery) {
      setQuery(urlQuery)
      setSubmitted(urlQuery)
    }
  }, [searchParams])

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitted(query.trim())
  }

  function exportCSV() {
    if (submitted) api.exportSearchCSV(submitted)
  }

  function exportJSON() {
    if (submitted) api.exportSearchJSON(submitted)
  }

  return (
    <>
      <PageHeader title="Busqueda documental" description="Busca por texto exacto, similitud semantica o mezcla hibrida con fuentes." />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardContent className="space-y-3 pt-4">
            <div className="flex flex-wrap gap-1 rounded-md border bg-muted p-1">
              {searchModes.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={item.id === mode ? "rounded bg-background px-3 py-1.5 text-sm shadow-sm" : "rounded px-3 py-1.5 text-sm"}
                  onClick={() => setMode(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <form className="flex gap-2" onSubmit={onSubmit}>
              <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ej. ABC123, pedido 2026/154, cliente X" />
              <Button disabled={!query.trim()}>
                <Search data-icon="inline-start" />
                Buscar
              </Button>
            </form>
            {submitted ? (
              <div className="flex flex-col gap-2 rounded-md border bg-slate-50 p-2 sm:flex-row">
                <Input className="h-9" value={savedName} onChange={(event) => setSavedName(event.target.value)} placeholder="Nombre de búsqueda guardada" />
                <Button variant="outline" size="sm" onClick={() => saveSearch.mutate()} disabled={saveSearch.isPending || !submitted}>
                  <Star data-icon="inline-start" />
                  Guardar
                </Button>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Búsquedas guardadas</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {(savedSearches.data ?? []).map((item) => (
              <button
                key={item.id}
                type="button"
                className="w-full rounded-md border p-3 text-left text-sm hover:bg-slate-50"
                onClick={() => {
                  setQuery(item.query)
                  setSubmitted(item.query)
                  setMode(toSearchMode(item.mode))
                }}
              >
                <span className="flex items-center gap-2 font-medium">
                  <Bookmark className="h-4 w-4 text-primary" />
                  {item.name}
                </span>
                <span className="mt-1 block truncate text-xs text-muted-foreground">{item.query}</span>
              </button>
            ))}
            {!savedSearches.data?.length ? <p className="text-sm text-muted-foreground">Sin búsquedas guardadas.</p> : null}
          </CardContent>
        </Card>
      </div>

      {submitted && results.data && results.data.length > 0 && (
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={exportCSV}>
            <Download data-icon="inline-start" />
            Exportar CSV
          </Button>
          <Button variant="outline" size="sm" onClick={exportJSON}>
            <FileJson data-icon="inline-start" />
            Exportar JSON
          </Button>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {(results.data ?? []).map((result, index) => (
          <Card key={`${result.document_id}-${result.page_number ?? "p"}-${result.block_id ?? "b"}-${result.source_type}-${index}`}>
            <CardHeader className="flex-row items-center justify-between gap-3">
              <div>
                <CardTitle>{result.original_filename}</CardTitle>
                <p className="mt-1 text-sm text-muted-foreground">
                  Pagina {result.page_number ?? "-"} · {result.document_type} · {result.source_type} · Score {result.score.toFixed(2)} · OCR{" "}
                  {result.ocr_confidence != null ? `${Math.round(result.ocr_confidence * 100)}%` : "-"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge status={result.status} />
                <Button asChild variant="outline" size="sm">
                  <Link to={`/documents/${result.document_id}`}>
                    <ExternalLink data-icon="inline-start" />
                    Abrir fuente
                  </Link>
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-6">{result.excerpt}</p>
            </CardContent>
          </Card>
        ))}
        {submitted && !results.isLoading && !results.data?.length ? (
          <p className="rounded-md border bg-card p-4 text-sm text-muted-foreground">Sin resultados.</p>
        ) : null}
      </div>
    </>
  )
}

type SearchMode = "hybrid" | "text" | "semantic" | "guided:budget" | "guided:order" | "guided:reference" | "guided:client" | "guided:supplier"

const searchModes: { id: SearchMode; label: string }[] = [
  { id: "hybrid", label: "Hibrida" },
  { id: "text", label: "Textual" },
  { id: "semantic", label: "Semantica" },
  { id: "guided:budget", label: "Presupuesto exacto" },
  { id: "guided:order", label: "Pedido exacto" },
  { id: "guided:reference", label: "Referencia" },
  { id: "guided:client", label: "Cliente" },
  { id: "guided:supplier", label: "Proveedor" },
]

function toSearchMode(value: string): SearchMode {
  return searchModes.some((item) => item.id === value) ? (value as SearchMode) : "hybrid"
}
