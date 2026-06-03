import { FormEvent, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Copy,
  Download,
  ExternalLink,
  FileSpreadsheet,
  History,
  MessageCircle,
  Plus,
  Send,
  ThumbsDown,
  X,
} from "lucide-react"

import { api } from "@/api/client"
import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { EmptyState } from "@/components/layout/EmptyState"
import { PageHeader } from "@/components/layout/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { formatDate } from "@/lib/utils"
import type { AIAnswer } from "@/types/api"

// ---------------------------------------------------------------------------
// Parsed answer sections
// ---------------------------------------------------------------------------
type AnswerSection = {
  type: "respuesta" | "datos" | "fuentes" | "confianza" | "advertencias" | "other"
  title: string
  content: string
}

function parseSections(raw: string): AnswerSection[] {
  const sections: AnswerSection[] = []
  const lines = raw.split("\n")
  let currentType: AnswerSection["type"] = "other"
  let currentTitle = ""
  let currentLines: string[] = []

  const sectionHeaders: Record<string, AnswerSection["type"]> = {
    respuesta: "respuesta",
    datos: "datos",
    fuentes: "fuentes",
    confianza: "confianza",
    advertencias: "advertencias",
    warnings: "advertencias",
  }

  for (const line of lines) {
    const trimmed = line.trim()
    // Detect section header: "**Respuesta**", "# Respuesta", "Respuesta:"
    const headerMatch = trimmed.match(/^(?:\*{1,2}|#{1,3}\s*)?(\w[\w\s]*?)(?:\*{1,2})?\s*:?\s*$/i)
    if (headerMatch) {
      const key = headerMatch[1].toLowerCase().trim()
      if (sectionHeaders[key]) {
        // Save previous section
        if (currentLines.length > 0) {
          sections.push({ type: currentType, title: currentTitle, content: currentLines.join("\n").trim() })
        }
        currentType = sectionHeaders[key]
        currentTitle = headerMatch[1].trim()
        currentLines = []
        continue
      }
    }
    currentLines.push(line)
  }

  // Save last section
  if (currentLines.length > 0) {
    sections.push({ type: currentType, title: currentTitle, content: currentLines.join("\n").trim() })
  }

  // If no sections detected, treat everything as "respuesta"
  if (sections.length === 0) {
    sections.push({ type: "respuesta", title: "Respuesta", content: raw.trim() })
  }

  return sections
}

function getSection(sections: AnswerSection[], type: AnswerSection["type"]): AnswerSection | undefined {
  return sections.find((s) => s.type === type)
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export function ChatPage() {
  const [question, setQuestion] = useState("")
  const [mode, setMode] = useState("hybrid")
  const [supplier, setSupplier] = useState("")
  const [documentType, setDocumentType] = useState("")
  const [answers, setAnswers] = useState<Array<{ question: string; answer: AIAnswer }>>([])
  const [markedIncorrect, setMarkedIncorrect] = useState<Set<number>>(new Set())
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

  function copyAnswer(answer: AIAnswer) {
    navigator.clipboard.writeText(answer.answer).catch(() => {})
  }

  function exportToExcel(answer: AIAnswer) {
    const rows = [["Pregunta", "Respuesta", "Confianza", "Fuentes", "Modelo", "Fecha"]]
    const sources = answer.sources.map((s) => `Doc #${s.document_id ?? "-"} Pág.${s.page_number ?? "-"}: ${s.excerpt ?? "-"}`).join(" | ")
    rows.push([answers.find((a) => a.answer.id === answer.id)?.question ?? "-", answer.answer, answer.confidence != null ? `${Math.round(answer.confidence * 100)}%` : "-", sources, answer.model_name ?? "-", formatDate(answer.created_at)])
    const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n")
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = `docu-intel-respuesta-${answer.id}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  function createTask(answer: AIAnswer) {
    const q = answers.find((a) => a.answer.id === answer.id)?.question ?? "Pregunta IA"
    api.createWorkItem({
      kind: "manual",
      title: `Verificar respuesta IA: ${q.slice(0, 80)}`,
      description: `Revisar la respuesta de la IA a la pregunta: "${q}"\n\nRespuesta: ${answer.answer.slice(0, 300)}...`,
      priority: "normal",
    }).then(() => {
      history.refetch()
    }).catch(() => {})
  }

  function markIncorrect(answerId: number) {
    setMarkedIncorrect((prev) => new Set(prev).add(answerId))
  }

  function hasSufficientSources(answer: AIAnswer): boolean {
    return answer.sources.length >= 1
  }

  return (
    <>
      <PageHeader title="Preguntar a documentos" description="Consulta la base documental con IA. Cada respuesta incluye fuentes verificables para que puedas comprobar los datos." />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        {/* Main */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px] font-semibold">Haz una pregunta</CardTitle>
              <CardDescription>La IA buscará en los documentos indexados y responderá solo con información encontrada.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-2 sm:grid-cols-3">
                <select className="h-9 rounded-md border bg-background px-3 text-sm" value={mode} onChange={(e) => setMode(e.target.value)}>
                  <option value="hybrid">Búsqueda híbrida</option>
                  <option value="semantic">Búsqueda semántica</option>
                  <option value="budget">Solo presupuestos</option>
                  <option value="order">Solo pedidos</option>
                </select>
                <Input value={supplier} onChange={(e) => setSupplier(e.target.value)} placeholder="Filtrar por proveedor" className="h-9" />
                <Input value={documentType} onChange={(e) => setDocumentType(e.target.value)} placeholder="Filtrar por tipo documental" className="h-9" />
              </div>
              <form className="flex gap-2" onSubmit={onSubmit}>
                <Input
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="Ej. ¿Qué presupuestos superan los 10.000 € este mes? ¿Cuántos pedidos hay del proveedor X?"
                  className="h-9 flex-1"
                />
                <Button disabled={!question.trim() || ask.isPending} className="h-9 gap-1.5">
                  <Send className="h-4 w-4" />
                  Preguntar
                </Button>
              </form>
              {ask.isError && <p className="text-sm text-destructive">{ask.error.message}</p>}
            </CardContent>
          </Card>

          {/* Answers */}
          {!answers.length && !ask.isPending && (
            <Card>
              <CardContent className="flex items-center gap-3 py-6 text-sm text-[var(--text-muted)]">
                <Bot className="h-5 w-5" />
                <span>Las respuestas aparecerán aquí con fuentes verificables. La IA solo responde con datos encontrados en los documentos.</span>
              </CardContent>
            </Card>
          )}

          {ask.isPending && (
            <Card>
              <CardContent className="flex items-center gap-3 py-6 text-sm text-[var(--text-muted)]">
                <Bot className="h-5 w-5 animate-pulse" />
                <span>Buscando en los documentos y generando respuesta...</span>
              </CardContent>
            </Card>
          )}

          <div className="space-y-4">
            {answers.map((item) => {
              const sections = parseSections(item.answer.answer)
              const respuesta = getSection(sections, "respuesta")
              const datos = getSection(sections, "datos")
              const advertencias = getSection(sections, "advertencias")
              const confianza = getSection(sections, "confianza")
              const sufficientSources = hasSufficientSources(item.answer)
              const isIncorrect = markedIncorrect.has(item.answer.id)

              return (
                <Card key={item.answer.id} className={cn(isIncorrect && "opacity-60")}>
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <CardTitle className="text-[14px]">{item.question}</CardTitle>
                        <CardDescription className="mt-1">
                          <span className="inline-flex items-center gap-2">
                            {item.answer.model_name && <span>Modelo: {item.answer.model_name}</span>}
                            {item.answer.confidence != null && (
                              <ConfidenceBadge value={item.answer.confidence} />
                            )}
                          </span>
                        </CardDescription>
                      </div>
                      {isIncorrect && (
                        <Badge variant="warning" className="flex-shrink-0 gap-1">
                          <ThumbsDown className="h-3 w-3" />
                          Marcada como incorrecta
                        </Badge>
                      )}
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {/* Anti-invention warning */}
                    {!sufficientSources && (
                      <div className="flex items-start gap-3 rounded-lg border border-[var(--amber-light)] bg-[var(--amber-light)]/40 p-4">
                        <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-[var(--amber)]" />
                        <div>
                          <p className="text-[13px] font-semibold text-[#92400E]">No hay evidencia suficiente</p>
                          <p className="mt-1 text-[12px] text-[#92400E]/80">
                            No se han encontrado fuentes documentales suficientes para responder a esta pregunta. La respuesta puede ser incompleta o no verificable.
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Answer sections */}
                    <div className="space-y-4">
                      {/* Respuesta */}
                      {respuesta && (
                        <div>
                          <h4 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Respuesta</h4>
                          <div className="rounded-md border bg-slate-50 p-4 text-[14px] leading-6 whitespace-pre-wrap text-[var(--text-primary)]">
                            {respuesta.content}
                          </div>
                        </div>
                      )}

                      {/* Datos */}
                      {datos && (
                        <div>
                          <h4 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">Datos encontrados</h4>
                          <div className="rounded-md border border-[var(--sky-light)] bg-[var(--sky-light)]/20 p-4 text-[13px] leading-6 whitespace-pre-wrap text-[var(--text-secondary)]">
                            {datos.content}
                          </div>
                        </div>
                      )}

                      {/* Advertencias */}
                      {advertencias && (
                        <div>
                          <h4 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-[var(--amber)]">Advertencias</h4>
                          <div className="rounded-md border border-[var(--amber-light)] bg-[var(--amber-light)]/20 p-4 text-[13px] leading-6 whitespace-pre-wrap text-[#92400E]">
                            {advertencias.content}
                          </div>
                        </div>
                      )}

                      {/* Other sections (not parsed) */}
                      {sections.filter((s) => !["respuesta", "datos", "fuentes", "confianza", "advertencias"].includes(s.type)).map((s, i) => (
                        <div key={i}>
                          <h4 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{s.title}</h4>
                          <div className="rounded-md border bg-slate-50 p-4 text-[13px] leading-6 whitespace-pre-wrap text-[var(--text-secondary)]">{s.content}</div>
                        </div>
                      ))}
                    </div>

                    {/* Sources */}
                    {item.answer.sources.length > 0 && (
                      <div>
                        <h4 className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                          Fuentes ({item.answer.sources.length})
                        </h4>
                        <div className="space-y-2">
                          {item.answer.sources.map((source) => (
                            <div key={source.id} className="flex items-start justify-between gap-3 rounded-md border bg-white p-3 text-sm">
                              <div className="min-w-0">
                                <p className="text-[13px] font-medium">
                                  Documento #{source.document_id ?? "—"}
                                  {source.page_number != null && <span> · Página {source.page_number}</span>}
                                  {source.block_id != null && <span> · Bloque {source.block_id}</span>}
                                </p>
                                {source.excerpt && (
                                  <p className="mt-1 line-clamp-2 text-[12px] text-[var(--text-muted)]">{source.excerpt}</p>
                                )}
                                {source.relevance_score != null && (
                                  <p className="mt-1 text-[10px] text-[var(--text-muted)]">
                                    Relevancia: {Math.round(source.relevance_score * 100)}%
                                  </p>
                                )}
                              </div>
                              {source.document_id && (
                                <Button asChild variant="outline" size="sm" className="h-7 text-xs flex-shrink-0">
                                  <Link to={`/documents/${source.document_id}`}>
                                    <ExternalLink className="mr-1 h-3 w-3" />
                                    Abrir
                                  </Link>
                                </Button>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Action buttons */}
                    <div className="flex flex-wrap gap-1.5 border-t pt-3">
                      <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={() => copyAnswer(item.answer)}>
                        <Copy className="h-3 w-3" />
                        Copiar respuesta
                      </Button>
                      <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={() => exportToExcel(item.answer)}>
                        <FileSpreadsheet className="h-3 w-3" />
                        Exportar Excel
                      </Button>
                      <Button variant="outline" size="sm" className="h-7 text-xs gap-1" onClick={() => createTask(item.answer)}>
                        <Plus className="h-3 w-3" />
                        Crear tarea
                      </Button>
                      {!isIncorrect && (
                        <Button variant="outline" size="sm" className="h-7 text-xs gap-1 text-[var(--amber)]" onClick={() => markIncorrect(item.answer.id)}>
                          <ThumbsDown className="h-3 w-3" />
                          Marcar incorrecta
                        </Button>
                      )}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px] font-semibold flex items-center gap-2">
                <History className="h-4 w-4" />
                Historial
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {(history.data ?? []).slice(0, 10).map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="w-full rounded-md border p-2.5 text-left text-sm hover:bg-slate-50 transition-colors"
                  onClick={() => setQuestion(item.question)}
                >
                  <span className="line-clamp-2 text-[13px]">{item.question}</span>
                  <span className="mt-1 block text-xs text-[var(--text-muted)]">{formatDate(item.created_at)}</span>
                </button>
              ))}
              {!history.data?.length && <p className="text-sm text-[var(--text-muted)]">Sin historial reciente.</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-[14px] font-semibold flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-[var(--amber)]" />
                Importante
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-[var(--text-secondary)]">
              <p>· La IA solo responde con datos encontrados en los documentos.</p>
              <p>· Si no hay fuentes suficientes, se mostrará una advertencia.</p>
              <p>· Verifica siempre las fuentes antes de tomar decisiones.</p>
              <p>· Marca las respuestas incorrectas para ayudarnos a mejorar.</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function composeQuestion(question: string, filters: { supplier: string; documentType: string }) {
  const clauses = [
    filters.supplier.trim() ? `proveedor: ${filters.supplier.trim()}` : "",
    filters.documentType.trim() ? `tipo documental: ${filters.documentType.trim()}` : "",
  ].filter(Boolean)
  return clauses.length ? `${question}\n\nFiltros: ${clauses.join("; ")}` : question
}
