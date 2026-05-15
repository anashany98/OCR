import { FormEvent, useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Download, ExternalLink, FileJson, Search } from "lucide-react"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"

export function SearchPage() {
  const [query, setQuery] = useState("")
  const [submitted, setSubmitted] = useState("")
  const [mode, setMode] = useState<"text" | "semantic" | "hybrid">("hybrid")
  const results = useQuery({
    queryKey: ["search", mode, submitted],
    queryFn: () => {
      if (mode === "semantic") return api.semanticSearch(submitted)
      if (mode === "hybrid") return api.hybridSearch(submitted)
      return api.textSearch(submitted)
    },
    enabled: submitted.length > 0,
  })

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitted(query.trim())
  }

  function exportCSV() {
    if (submitted) {
      api.exportSearchCSV(submitted)
    }
  }

  function exportJSON() {
    if (submitted) {
      api.exportSearchJSON(submitted)
    }
  }

  return (
    <>
      <PageHeader title="Busqueda documental" description="Busca por texto exacto, similitud semantica o mezcla hibrida con fuentes." />
      <Card>
        <CardContent className="space-y-3 pt-4">
          <div className="inline-flex rounded-md border bg-muted p-1">
            {(["hybrid", "text", "semantic"] as const).map((item) => (
              <button
                key={item}
                type="button"
                className={item === mode ? "bg-background shadow-sm rounded px-3 py-1.5 text-sm" : "rounded px-3 py-1.5 text-sm"}
                onClick={() => setMode(item)}
              >
                {item === "hybrid" ? "Hibrida" : item === "semantic" ? "Semantica" : "Textual"}
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
        </CardContent>
      </Card>

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
