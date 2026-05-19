import { FormEvent, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Bot, Download, ExternalLink, History, Send } from "lucide-react"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { formatDate } from "@/lib/utils"
import type { AIAnswer } from "@/types/api"

export function ChatPage() {
  const [question, setQuestion] = useState("")
  const [mode, setMode] = useState("hybrid")
  const [supplier, setSupplier] = useState("")
  const [documentType, setDocumentType] = useState("")
  const [answers, setAnswers] = useState<Array<{ question: string; answer: AIAnswer }>>([])
  const history = useQuery({ queryKey: ["ai-history"], queryFn: api.aiHistory, refetchInterval: 30000 })
  const ask = useMutation({
    mutationFn: (value: string) => api.askAI(composeQuestion(value, { supplier, documentType }), mode),
    onSuccess: (answer, value) => {
      setAnswers((current) => [{ question: value, answer }, ...current])
      setQuestion("")
      history.refetch()
    },
  })

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const trimmed = question.trim()
    if (trimmed) ask.mutate(trimmed)
  }

  return (
    <>
      <PageHeader title="Chat IA" description="Consulta la base documental mediante herramientas internas controladas y respuestas con fuentes." />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <CardHeader>
            <CardTitle>Pregunta documental</CardTitle>
            <CardDescription>El backend recupera contexto documental y devuelve fuentes auditables.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-2 md:grid-cols-3">
              <select className="h-9 rounded-md border bg-background px-3 text-sm" value={mode} onChange={(event) => setMode(event.target.value)}>
                <option value="hybrid">Híbrido</option>
                <option value="semantic">Semántico</option>
                <option value="budget">Presupuesto</option>
                <option value="order">Pedido</option>
              </select>
              <Input value={supplier} onChange={(event) => setSupplier(event.target.value)} placeholder="Filtro proveedor" />
              <Input value={documentType} onChange={(event) => setDocumentType(event.target.value)} placeholder="Tipo documental" />
            </div>
            <form className="flex gap-2" onSubmit={onSubmit}>
              <Input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Ej. ¿Qué documentos mencionan la referencia ABC123?"
              />
              <Button disabled={!question.trim() || ask.isPending}>
                <Send data-icon="inline-start" />
                Preguntar
              </Button>
            </form>
            {ask.isError ? <p className="text-sm text-destructive">{ask.error.message}</p> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <History className="h-4 w-4" />
              Historial
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {(history.data ?? []).slice(0, 8).map((item) => (
              <button key={item.id} type="button" className="w-full rounded-md border p-2 text-left text-sm hover:bg-slate-50" onClick={() => setQuestion(item.question)}>
                <span className="line-clamp-2">{item.question}</span>
                <span className="mt-1 block text-xs text-muted-foreground">{formatDate(item.created_at)}</span>
              </button>
            ))}
            {!history.data?.length ? <p className="text-sm text-muted-foreground">Sin historial reciente.</p> : null}
          </CardContent>
        </Card>
      </div>

      {!answers.length ? (
        <Card>
          <CardContent className="flex items-center gap-3 p-4 text-sm text-muted-foreground">
            <Bot />
            <span>Las respuestas aparecerán con datos, fuentes, confianza y advertencias.</span>
          </CardContent>
        </Card>
      ) : null}

      <div className="flex flex-col gap-4">
        {answers.map((item) => (
          <Card key={item.answer.id}>
            <CardHeader className="flex-row items-start justify-between gap-3">
              <div>
                <CardTitle className="text-base">{item.question}</CardTitle>
                <CardDescription>
                  Modelo: {item.answer.model_name ?? "-"} · Confianza{" "}
                  {item.answer.confidence !== null ? `${Math.round(item.answer.confidence * 100)}%` : "-"}
                </CardDescription>
              </div>
              <Button variant="outline" size="sm" onClick={() => exportAnswer(item.answer)}>
                <Download data-icon="inline-start" />
                Exportar
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <pre className="whitespace-pre-wrap rounded-md border bg-muted p-4 text-sm leading-6">{item.answer.answer}</pre>
              {item.answer.sources.length ? (
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold">Fuentes</h3>
                  {item.answer.sources.map((source) => (
                    <div key={source.id} className="flex items-start justify-between gap-3 rounded-md border p-3 text-sm">
                      <div>
                        <p className="font-medium">
                          Documento #{source.document_id ?? "-"} · Página {source.page_number ?? "-"} · Bloque {source.block_id ?? "-"}
                        </p>
                        <p className="mt-1 line-clamp-2 text-muted-foreground">{source.excerpt ?? "Sin extracto."}</p>
                      </div>
                      {source.document_id ? (
                        <Button asChild variant="outline" size="sm">
                          <Link to={`/documents/${source.document_id}`}>
                            <ExternalLink data-icon="inline-start" />
                            Abrir
                          </Link>
                        </Button>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  )
}

function composeQuestion(question: string, filters: { supplier: string; documentType: string }) {
  const clauses = [
    filters.supplier.trim() ? `proveedor: ${filters.supplier.trim()}` : "",
    filters.documentType.trim() ? `tipo documental: ${filters.documentType.trim()}` : "",
  ].filter(Boolean)
  return clauses.length ? `${question}\n\nFiltros: ${clauses.join("; ")}` : question
}

function exportAnswer(answer: AIAnswer) {
  const blob = new Blob([JSON.stringify(answer, null, 2)], { type: "application/json" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = `docu-intel-answer-${answer.id}.json`
  link.click()
  URL.revokeObjectURL(url)
}
