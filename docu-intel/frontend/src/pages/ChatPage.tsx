import {
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Building2,
  ChevronDown,
  ChevronUp,
  Copy,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  History,
  ImageIcon,
  Link2,
  Loader2,
  Map as MapIcon,
  MessageCircle,
  Plus,
  Receipt,
  Send,
  Sparkles,
  ThumbsDown,
  Trash2,
  User as UserIcon,
  X,
} from "lucide-react"

import { api } from "@/api/client"
import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { EmptyChatIllustration } from "@/components/illustrations/EditorialIllustrations"
import { PageHeader } from "@/components/layout/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { cn, formatMoney } from "@/lib/utils"
import { formatDate } from "@/lib/utils"
import { notify } from "@/lib/toast"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { thumbnailUrl, pageImageUrl } from "@/api/core"
import type { AIAnswer, AIQuestion, ResolvedDocument, ResolvedDocumentEntity } from "@/types/api"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type ChatRole = "user" | "assistant"

type ChatMessage = {
  /** Stable local id for React keys. */
  id: string
  role: ChatRole
  content: string
  createdAt: string
  /** The user's question that produced this message. Set on assistant messages. */
  question?: string
  /** Set only on assistant messages. */
  answer?: AIAnswer
  /** True while the request is in flight (assistant placeholder). */
  pending?: boolean
  /** Set when the assistant message has been marked as wrong by the user. */
  markedIncorrect?: boolean
}

const STORAGE_KEY = "docu-intel:chat:messages:v1"

// ---------------------------------------------------------------------------
// Tiny safe markdown renderer for the assistant's natural-prose response.
// ---------------------------------------------------------------------------
// Supports the small subset that the LLM is allowed to emit:
//   - paragraphs (separated by blank lines)
//   - **bold** and *italic* inline
//   - `inline code`
//   - unordered lists (- item or * item)
//   - block quotes (> quote)
// No HTML is allowed through; all output is plain text wrapped in our own
// elements. The renderer is intentionally conservative so a hostile LLM
// cannot inject scripts or break the layout.
function renderInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = []
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g
  let lastIndex = 0
  let match: RegExpExecArray | null
  let key = 0
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }
    const raw = match[0]
    if (raw.startsWith("**")) {
      parts.push(<strong key={key++} className="font-semibold text-[var(--text-primary)]">{raw.slice(2, -2)}</strong>)
    } else if (raw.startsWith("*")) {
      parts.push(<em key={key++} className="italic">{raw.slice(1, -1)}</em>)
    } else if (raw.startsWith("`")) {
      parts.push(<code key={key++} className="rounded bg-[var(--bg-surface-2)] px-1 py-0.5 font-mono text-[12px]">{raw.slice(1, -1)}</code>)
    }
    lastIndex = regex.lastIndex
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }
  return parts
}

type Block = { kind: "p" | "ul" | "quote"; lines: string[] }

function splitBlocks(text: string): Block[] {
  const blocks: Block[] = []
  let current: Block | null = null
  const flush = () => {
    if (current && current.lines.some((l) => l.trim().length > 0)) {
      blocks.push(current)
    }
    current = null
  }
  for (const rawLine of text.split("\n")) {
    const line = rawLine.replace(/\s+$/, "")
    if (!line.trim()) {
      flush()
      continue
    }
    const isBullet = /^[-*]\s+/.test(line)
    const isQuote = /^>\s?/.test(line)
    let kind: Block["kind"] = "p"
    let content = line
    if (isBullet) {
      kind = "ul"
      content = line.replace(/^[-*]\s+/, "")
    } else if (isQuote) {
      kind = "quote"
      content = line.replace(/^>\s?/, "")
    }
    if (!current || current.kind !== kind) {
      flush()
      current = { kind, lines: [content] }
    } else {
      current.lines.push(content)
    }
  }
  flush()
  return blocks
}

function renderAssistantContent(text: string) {
  const blocks = splitBlocks(text)
  if (blocks.length === 0) {
    return <p className="whitespace-pre-wrap leading-relaxed">{text}</p>
  }
  return (
    <div className="space-y-3 text-[14.5px] leading-relaxed">
      {blocks.map((b, i) => {
        if (b.kind === "ul") {
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {b.lines.map((line, j) => (
                <li key={j}>{renderInline(line)}</li>
              ))}
            </ul>
          )
        }
        if (b.kind === "quote") {
          return (
            <blockquote
              key={i}
              className="border-l-2 border-[var(--accent)] bg-[var(--accent-faint)]/60 px-3 py-2 italic text-[var(--text-secondary)]"
            >
              {b.lines.map((line, j) => (
                <p key={j} className={j === 0 ? "" : "mt-1"}>{renderInline(line)}</p>
              ))}
            </blockquote>
          )
        }
        return (
          <p key={i} className="whitespace-pre-wrap">{renderInline(b.lines.join(" "))}</p>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
const SUGGESTED_PROMPTS = [
  "¿Qué presupuestos superan los 10.000 € este mes?",
  "Resumen de los pedidos del proveedor García",
  "¿Hay planos sin escala válida pendientes de revisar?",
  "¿Cuántos documentos con baja confianza OCR hay ahora mismo?",
]

export function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [hydrated, setHydrated] = useState(false)
  const [draft, setDraft] = useState("")
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [mode, setMode] = useState("hybrid")
  const [supplier, setSupplier] = useState("")
  const [documentType, setDocumentType] = useState("")
  const [markedIncorrect, setMarkedIncorrect] = useState<Set<string>>(new Set())

  const history = useQuery({ queryKey: ["ai-history"], queryFn: api.aiHistory, refetchInterval: 30000 })
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Load conversation from localStorage on mount.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) {
        const parsed = JSON.parse(raw) as ChatMessage[]
        if (Array.isArray(parsed)) setMessages(parsed)
      }
    } catch {
      // ignore corrupted storage
    }
    setHydrated(true)
  }, [])

  // Streaming send. We keep streaming state at the component level (not
  // inside useMutation) so we can append chunks as they arrive instead of
  // waiting for the whole response.
  const [isStreaming, setIsStreaming] = useState(false)
  const streamControllerRef = useRef<AbortController | null>(null)

  async function sendStream(value: string) {
    const trimmed = value.trim()
    if (!trimmed || isStreaming) return
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmed,
      createdAt: new Date().toISOString(),
    }
    const pendingId = `assistant-${Date.now()}-pending`
    const pendingMsg: ChatMessage = {
      id: pendingId,
      role: "assistant",
      content: "",
      createdAt: new Date().toISOString(),
      question: trimmed,
      pending: true,
    }
    setMessages((current) => [...current, userMsg, pendingMsg])
    setDraft("")
    setIsStreaming(true)
    history.refetch()

    const controller = new AbortController()
    streamControllerRef.current = controller
    let assembled = ""
    let resolved: AIAnswer["resolved_document"] = null
    let confidence: number | null = null
    let modelName: string | null = null
    let followups: string[] = []
    let sources: NonNullable<AIAnswer["sources"]> = []
    let dbId: number | null = null
    let usedFallback = false
    let thinkingPieces = 0

    try {
      for await (const ev of api.askAIStream(
        composeQuestion(trimmed, { supplier, documentType }),
        mode,
        controller.signal,
      )) {
        if (ev.type === "thinking") {
          // Reasoning models (Qwen3) emit "thinking" tokens before the
          // final answer. We count them and use that to flip the UI from
          // "pensando" to "razonando..." so the user knows the model is
          // working on a non-trivial query.
          thinkingPieces += 1
          if (thinkingPieces === 1) {
            setMessages((current) => {
              const idx = current.findIndex((m) => m.id === pendingId)
              if (idx === -1) return current
              const next = [...current]
              next[idx] = { ...next[idx], content: "razonando…" }
              return next
            })
          }
        } else if (ev.type === "delta") {
          assembled += ev.text
          setMessages((current) => {
            const idx = current.findIndex((m) => m.id === pendingId)
            if (idx === -1) return current
            const next = [...current]
            next[idx] = { ...next[idx], content: assembled }
            return next
          })
        } else if (ev.type === "end") {
          assembled = ev.answer
          resolved = ev.resolved_document
          confidence = ev.confidence
          modelName = ev.model
          followups = ev.followups
          sources = ev.sources
          usedFallback = ev.fallback
          dbId = (ev as { answer_id?: number }).answer_id ?? null
        }
      }
    } catch (err) {
      setMessages((current) => {
        const idx = current.findIndex((m) => m.id === pendingId)
        if (idx === -1) return current
        const next = [...current]
        next[idx] = {
          ...next[idx],
          content: assembled || "Lo siento, no he podido completar la busqueda. Revisa tu conexion o intentalo de nuevo en unos segundos.",
          pending: false,
        }
        return next
      })
      notify.error(err as Error, "La IA no pudo responder")
      return
    } finally {
      setIsStreaming(false)
      streamControllerRef.current = null
    }

    // Finalise the assistant message: replace the pending placeholder with
    // a fully-populated AIAnswer so the card / followups / etc. render.
    setMessages((current) => {
      const idx = current.findIndex((m) => m.id === pendingId)
      if (idx === -1) return current
      const next = [...current]
      const fullAnswer: AIAnswer = {
        id: dbId ?? 0,
        question_id: 0,
        answer: assembled,
        confidence,
        model_name: modelName,
        resolved_document: resolved,
        followups,
        created_at: new Date().toISOString(),
        sources,
      }
      next[idx] = {
        ...next[idx],
        content: assembled,
        answer: fullAnswer,
        pending: false,
      }
      return next
    })
    history.refetch()
    if (usedFallback) {
      notify.info("Usando fallback estructurado", "El LLM no respondio; mostramos el resumen grounded.")
    } else if (confidence != null && confidence < 0.5) {
      notify.warning("Respuesta con baja confianza", "La IA no encontró evidencia sólida. Verifica las fuentes.")
    }
  }

  // Persist conversation (skip transient pending markers).
  useEffect(() => {
    if (!hydrated) return
    try {
      const slim = messages.map((m) => ({ ...m, pending: false }))
      localStorage.setItem(STORAGE_KEY, JSON.stringify(slim))
    } catch {
      // quota / private mode — non-fatal
    }
  }, [messages, hydrated])

  // Auto-scroll to bottom whenever messages change or a new pending appears.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: isStreaming ? "smooth" : "auto" })
  }, [messages, isStreaming])

  const isComposing = useRef(false)

  const send = useCallback(
    (value: string) => {
      void sendStream(value)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [isStreaming],
  )

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    send(draft)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !isComposing.current) {
      event.preventDefault()
      send(draft)
    }
  }

  // Auto-resize textarea up to a max height.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = Math.min(el.scrollHeight, 180) + "px"
  }, [draft])

  function clearConversation() {
    if (!messages.length) return
    if (!confirm("¿Borrar toda la conversacion?")) return
    setMessages([])
    setMarkedIncorrect(new Set())
    try { localStorage.removeItem(STORAGE_KEY) } catch {}
  }

  function copyAnswer(message: ChatMessage) {
    if (!message.answer) return
    navigator.clipboard.writeText(message.answer.answer).catch(() => {})
    notify.success("Respuesta copiada al portapapeles")
  }

  function exportToExcel(message: ChatMessage) {
    if (!message.answer) return
    const a = message.answer
    const rows = [["Pregunta", "Respuesta", "Confianza", "Fuentes", "Modelo", "Fecha"]]
    const sources = a.sources.map((s) => `Doc #${s.document_id ?? "-"} Pág.${s.page_number ?? "-"}: ${s.excerpt ?? "-"}`).join(" | ")
    rows.push([message.content, a.answer, a.confidence != null ? `${Math.round(a.confidence * 100)}%` : "-", sources, a.model_name ?? "-", formatDate(a.created_at)])
    const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n")
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = `docu-intel-respuesta-${a.id}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  function createTask(message: ChatMessage) {
    if (!message.answer) return
    const question = (message.question || "").trim() || "Pregunta IA"
    // Extract only the conversational "Respuesta:" prose for the description,
    // not the whole structured audit block.
    const respuestaMatch = message.answer.answer.match(/\*\*Respuesta:\*\*\s*([\s\S]*?)(?=\n\n\*\*|$)/)
    const respuestaProse = (respuestaMatch ? respuestaMatch[1] : message.answer.answer).trim()
    const truncatedProse = respuestaProse.length > 500
      ? respuestaProse.slice(0, 500) + "…"
      : respuestaProse
    api.createWorkItem({
      kind: "manual",
      title: `Revisar respuesta IA: ${question.slice(0, 80)}`,
      description: [
        `Pregunta del usuario: ${question}`,
        "",
        "Respuesta de la IA:",
        truncatedProse,
        "",
        `Fuentes citadas: ${message.answer.sources.length}`,
        `Confianza: ${message.answer.confidence != null ? Math.round(message.answer.confidence * 100) + "%" : "n/d"}`,
        `Modelo: ${message.answer.model_name ?? "n/d"}`,
      ].join("\n"),
      priority: "normal",
    }).then(() => {
      history.refetch()
      notify.success("Tarea creada para revisar la respuesta")
    }).catch((err) => notify.error(err, "No se pudo crear la tarea"))
  }

  /**
   * Re-run the last user question so the user gets a fresh answer (useful
   * when the LLM produces a low-quality response). The old assistant
   * message is removed and a new one takes its place.
   */
  function regenerate(assistantMessage: ChatMessage) {
    if (isStreaming) return
    const question = (assistantMessage.question || "").trim()
    if (!question) return
    notify.info("Regenerando respuesta", "Volviendo a lanzar la consulta al modelo.")
    setMessages((current) => current.filter((m) => m.id !== assistantMessage.id))
    setDraft("")
    void sendStream(question)
  }

  function markIncorrect(id: string) {
    setMarkedIncorrect((prev) => new Set(prev).add(id))
  }

  const hasMessages = messages.length > 0

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Breadcrumbs items={[{ label: "Preguntar a documentos" }]} />
      <PageHeader
        title="Preguntar a documentos"
        description="Conversa con la base documental. Cada respuesta cita sus fuentes para que puedas comprobarla."
        variant="plain"
        actions={
          hasMessages ? (
            <Button variant="ghost" size="sm" onClick={clearConversation} className="gap-1.5 text-[var(--text-muted)] hover:text-[var(--danger)]">
              <Trash2 className="h-3.5 w-3.5" />
              Borrar conversacion
            </Button>
          ) : null
        }
      />

      <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        {/* Main chat column */}
        <div className="flex min-h-0 flex-col">
          <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
            {/* Scrollable conversation */}
            <div
              ref={scrollRef}
              className="min-h-0 flex-1 overflow-y-auto"
              style={{ scrollbarGutter: "stable" }}
            >
              <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6 sm:px-6">
                {!hasMessages && hydrated && <WelcomeCard onPick={(q) => { setDraft(q); textareaRef.current?.focus() }} />}

                {messages.map((m) => (
                  <MessageBubble
                    key={m.id}
                    message={m}
                    isIncorrect={markedIncorrect.has(m.id)}
                    onCopy={() => copyAnswer(m)}
                    onExport={() => exportToExcel(m)}
                    onTask={() => createTask(m)}
                    onRegenerate={() => regenerate(m)}
                    onMarkIncorrect={() => markIncorrect(m.id)}
                    onPickFollowup={(q) => { setDraft(q); textareaRef.current?.focus() }}
                  />
                ))}

                {isStreaming && !messages.some((m) => m.pending) && <TypingIndicator />}
              </div>
            </div>

            {/* Input area */}
            <div className="border-t border-[var(--border)] bg-[var(--bg-surface)] px-4 py-3 sm:px-6">
              <div className="mx-auto w-full max-w-3xl">
                <form onSubmit={onSubmit} className="flex items-end gap-2">
                  <div className="flex-1 rounded-2xl border border-[var(--border-2)] bg-[var(--bg-base)] shadow-paper transition-colors focus-within:border-[var(--accent)] focus-within:bg-[var(--bg-surface)]">
                    <textarea
                      ref={textareaRef}
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={onKeyDown}
                      onCompositionStart={() => { isComposing.current = true }}
                      onCompositionEnd={() => { isComposing.current = false }}
                      rows={1}
                      placeholder="Escribe tu pregunta…  (Enter para enviar, Shift+Enter para nueva linea)"
                      className="block w-full resize-none bg-transparent px-4 py-3 text-[14px] leading-relaxed text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none"
                      disabled={isStreaming}
                    />
                    <div className="flex items-center justify-between border-t border-[var(--border)]/60 px-2 py-1.5 text-[11px] text-[var(--text-muted)]">
                      <button
                        type="button"
                        onClick={() => setFiltersOpen((v) => !v)}
                        className="inline-flex items-center gap-1 rounded px-1.5 py-1 transition-colors hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-secondary)]"
                      >
                        {filtersOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                        <span>Filtros {activeFilterCount(supplier, documentType) > 0 && <span className="ml-0.5 rounded bg-[var(--accent-light)] px-1 text-[10px] font-semibold text-[var(--accent)]">{activeFilterCount(supplier, documentType)}</span>}</span>
                      </button>
                      <span className="hidden sm:inline">
                        {isStreaming ? (
                          <span className="inline-flex items-center gap-1 text-[var(--accent)]">
                            <Loader2 className="h-3 w-3 animate-spin" />
                            pensando...
                          </span>
                        ) : (
                          `${draft.length} caracteres`
                        )}
                      </span>
                    </div>
                  </div>
                  {isStreaming ? (
                    <Button
                      type="button"
                      onClick={() => streamControllerRef.current?.abort()}
                      className="h-11 w-11 flex-shrink-0 rounded-2xl p-0"
                      aria-label="Detener respuesta"
                      variant="outline"
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  ) : (
                    <Button
                      type="submit"
                      disabled={!draft.trim() || isStreaming}
                      className="h-11 w-11 flex-shrink-0 rounded-2xl p-0"
                      aria-label="Enviar pregunta"
                    >
                      <Send className="h-4 w-4" />
                    </Button>
                  )}
                </form>

                {filtersOpen && (
                  <div className="mt-2 grid gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)]/60 p-2 sm:grid-cols-3">
                    <select className="h-9 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 text-[13px]" value={mode} onChange={(e) => setMode(e.target.value)}>
                      <option value="hybrid">Búsqueda híbrida</option>
                      <option value="semantic">Búsqueda semántica</option>
                      <option value="budget">Solo presupuestos</option>
                      <option value="order">Solo pedidos</option>
                    </select>
                    <input
                      value={supplier}
                      onChange={(e) => setSupplier(e.target.value)}
                      placeholder="Filtrar por proveedor"
                      className="h-9 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 text-[13px] focus:border-[var(--accent)] focus:outline-none"
                    />
                    <input
                      value={documentType}
                      onChange={(e) => setDocumentType(e.target.value)}
                      placeholder="Filtrar por tipo documental"
                      className="h-9 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 text-[13px] focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>
                )}

                {isStreaming && messages.some((m) => m.pending) && (
                  <p className="mt-2 text-[12px] text-[var(--text-muted)]">
                    La IA está escribiendo. Pulsa <kbd className="rounded border border-[var(--border)] bg-[var(--bg-surface-2)] px-1 font-mono text-[10px]">×</kbd> para detener.
                  </p>
                )}
              </div>
            </div>
          </Card>
        </div>

        {/* Right sidebar */}
        <aside className="hidden min-h-0 flex-col gap-4 xl:flex">
          <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <CardContent className="flex min-h-0 flex-1 flex-col gap-3 p-0">
              <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-3 text-[13px] font-semibold">
                <History className="h-4 w-4 text-[var(--text-muted)]" />
                <span>Conversaciones recientes</span>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
                {(history.data ?? []).length === 0 ? (
                  <p className="px-2 py-3 text-[13px] text-[var(--text-muted)]">Sin historial reciente.</p>
                ) : (
                  <ul className="space-y-1">
                    {(history.data ?? []).slice(0, 12).map((item) => (
                      <li key={item.id}>
                        <HistoryRow item={item} onPick={(q) => { setDraft(q); textareaRef.current?.focus() }} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-2 px-4 py-4 text-[12.5px] text-[var(--text-secondary)]">
              <p className="flex items-center gap-1.5 text-[13px] font-semibold text-[var(--text-primary)]">
                <AlertTriangle className="h-3.5 w-3.5 text-[var(--warning)]" />
                Como trabaja la IA
              </p>
              <p>· Solo responde con datos encontrados en los documentos.</p>
              <p>· Si no hay fuentes, te avisa en vez de inventar.</p>
              <p>· Verifica siempre la fuente antes de tomar decisiones.</p>
              <p>· Marca como incorrecta si detectas un error, nos ayuda a mejorar.</p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------
function activeFilterCount(supplier: string, documentType: string) {
  let n = 0
  if (supplier.trim()) n++
  if (documentType.trim()) n++
  return n
}

function WelcomeCard({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="flex flex-col items-center gap-5 rounded-2xl border border-dashed border-[var(--border-2)] bg-[var(--bg-surface-2)]/30 px-6 py-8 text-center">
      <div className="flex h-32 w-40 items-center justify-center text-[var(--accent)]">
        <EmptyChatIllustration />
      </div>
      <div className="space-y-1.5">
        <h2 className="font-display text-[22px] font-medium tracking-tight text-[var(--text-primary)]">
          Hola, soy tu asistente documental
        </h2>
        <p className="mx-auto max-w-lg text-[13px] text-[var(--text-muted)]">
          Preguntame lo que quieras sobre los documentos del proyecto. Te respondo en lenguaje natural,
          entiendo PDFs, emails, planos e imagenes, y cito siempre la fuente para que puedas
          comprobarlo.
        </p>
      </div>
      <div className="grid w-full max-w-2xl gap-2 sm:grid-cols-2">
        {SUGGESTED_PROMPTS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => onPick(p)}
            className="group flex items-start gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2.5 text-left text-[13px] text-[var(--text-secondary)] transition-colors hover:border-[var(--accent)] hover:bg-[var(--bg-surface)] hover:text-[var(--text-primary)]"
          >
            <MessageCircle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-[var(--text-muted)] group-hover:text-[var(--accent)]" />
            <span className="leading-snug">{p}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex items-start gap-3">
      <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-[var(--accent-light)] text-[var(--accent)]">
        <Bot className="h-4 w-4" />
      </div>
      <div className="rounded-2xl rounded-tl-sm border border-[var(--border)] bg-[var(--bg-surface-2)]/60 px-4 py-3">
        <div className="flex items-center gap-1.5">
          <Dot delay="0ms" />
          <Dot delay="120ms" />
          <Dot delay="240ms" />
        </div>
      </div>
    </div>
  )
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="block h-1.5 w-1.5 rounded-full bg-[var(--text-muted)]"
      style={{
        animation: "chat-bounce 1.1s infinite ease-in-out",
        animationDelay: delay,
      }}
    />
  )
}

function HistoryRow({ item, onPick }: { item: AIQuestion; onPick: (q: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onPick(item.question)}
      className="flex w-full flex-col gap-0.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-[var(--bg-surface-2)]"
    >
      <span className="line-clamp-2 text-[13px] text-[var(--text-primary)]">{item.question}</span>
      <span className="text-[11px] text-[var(--text-muted)]">{formatDate(item.created_at)}</span>
    </button>
  )
}

function ActionButton({
  onClick,
  title,
  ariaLabel,
  children,
  hoverColor = "primary",
}: {
  onClick: () => void
  title: string
  ariaLabel: string
  children: React.ReactNode
  hoverColor?: "primary" | "warning"
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={ariaLabel}
      className={cn(
        "inline-flex h-6 w-6 items-center justify-center rounded transition-colors",
        "hover:bg-[var(--bg-surface-2)]",
        hoverColor === "warning"
          ? "hover:text-[var(--warning)]"
          : "hover:text-[var(--text-primary)]",
      )}
    >
      {children}
    </button>
  )
}


function MessageBubble({
  message,
  isIncorrect,
  onCopy,
  onExport,
  onTask,
  onRegenerate,
  onMarkIncorrect,
  onPickFollowup,
}: {
  message: ChatMessage
  isIncorrect: boolean
  onCopy: () => void
  onExport: () => void
  onTask: () => void
  onRegenerate: () => void
  onMarkIncorrect: () => void
  onPickFollowup: (q: string) => void
}) {
  const isUser = message.role === "user"
  const hasAnswer = !!message.answer
  const sources = message.answer?.sources ?? []
  const sufficient = sources.length > 0
  const resolved = message.answer?.resolved_document

  return (
    <div className={cn("flex items-start gap-3", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full",
          isUser
            ? "bg-[var(--ink)] text-[var(--bg-base)]"
            : "bg-[var(--accent-light)] text-[var(--accent)]",
        )}
      >
        {isUser ? <UserIcon className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      <div className={cn("flex min-w-0 flex-1 flex-col gap-1.5", isUser && "items-end")}>
        <div className={cn("flex items-center gap-2 text-[11px] text-[var(--text-muted)]", isUser && "flex-row-reverse")}>
          <span className="font-medium text-[var(--text-secondary)]">
            {isUser ? "Tu" : "Asistente Docu-Intel"}
          </span>
          <span>·</span>
          <span>{formatDate(message.createdAt)}</span>
          {hasAnswer && message.answer?.model_name && (
            <>
              <span>·</span>
              <span className="truncate max-w-[160px]">{message.answer.model_name}</span>
            </>
          )}
        </div>

        <div
          className={cn(
            "max-w-[88%] rounded-2xl px-4 py-3 text-[14.5px] leading-relaxed shadow-paper sm:max-w-[80%]",
            isUser
              ? "rounded-tr-sm bg-[var(--ink)] text-[var(--bg-base)]"
              : "rounded-tl-sm border border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-primary)]",
            isIncorrect && "opacity-60",
          )}
        >
          {message.pending ? (
            <TypingIndicatorInline />
          ) : isUser ? (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          ) : (
            <div className="space-y-2">
              {message.answer?.resolved_document && (
                <>
                  <ResolvedDocumentCard resolved={message.answer.resolved_document} />
                  <DocumentPreview
                    documentId={message.answer.resolved_document.document.id}
                    filename={message.answer.resolved_document.document.filename}
                  />
                </>
              )}
              {renderAssistantContent(message.content)}
            </div>
          )}
        </div>

        {/* Follow-up suggestions: shown only after the assistant finishes. */}
        {!isUser && !message.pending && (message.answer?.followups?.length ?? 0) > 0 && (
          <FollowupChips
            followups={message.answer!.followups}
            onPick={onPickFollowup}
          />
        )}

        {/* Assistant meta row: confidence, sources chips, compact actions */}
        {!isUser && hasAnswer && !message.pending && (
          <div className="flex max-w-[88%] flex-wrap items-center gap-1 sm:max-w-[80%]">
            {message.answer?.confidence != null && (
              <ConfidenceBadge value={message.answer.confidence} />
            )}
            {sources.length > 0 && (
              <Badge variant="neutral" className="gap-1">
                <ExternalLink className="h-3 w-3" />
                {sources.length} {sources.length === 1 ? "fuente" : "fuentes"}
              </Badge>
            )}
            {!sufficient && (
              <Badge variant="warning" className="gap-1">
                <AlertTriangle className="h-3 w-3" />
                Sin evidencia
              </Badge>
            )}
            {isIncorrect && (
              <Badge variant="warning" className="gap-1">
                <ThumbsDown className="h-3 w-3" />
                Marcada
              </Badge>
            )}

            <span className="mx-0.5 hidden h-3 w-px bg-[var(--border)] sm:inline-block" />

            <div className="inline-flex items-center gap-0.5 rounded-md p-0.5 text-[var(--text-muted)]">
              <ActionButton onClick={onCopy} title="Copiar respuesta" ariaLabel="Copiar respuesta">
                <Copy className="h-3 w-3" />
              </ActionButton>
              <ActionButton onClick={onExport} title="Exportar a CSV" ariaLabel="Exportar a CSV">
                <FileSpreadsheet className="h-3 w-3" />
              </ActionButton>
              <ActionButton onClick={onTask} title="Crear tarea de revisión" ariaLabel="Crear tarea de revisión">
                <Plus className="h-3 w-3" />
              </ActionButton>
              <ActionButton onClick={onRegenerate} title="Regenerar respuesta" ariaLabel="Regenerar respuesta">
                <Sparkles className="h-3 w-3" />
              </ActionButton>
              {!isIncorrect && (
                <ActionButton
                  onClick={onMarkIncorrect}
                  title="Marcar como incorrecta"
                  ariaLabel="Marcar como incorrecta"
                  hoverColor="warning"
                >
                  <ThumbsDown className="h-3 w-3" />
                </ActionButton>
              )}
            </div>
          </div>
        )}

        {/* Source list (compact) — only when there are sources */}
        {!isUser && hasAnswer && sources.length > 0 && !message.pending && (
          <div className="mt-0.5 flex max-w-[88%] flex-wrap gap-1.5 sm:max-w-[80%]">
            {sources.slice(0, 6).map((s) => (
              <SourceChip key={s.id} source={s} />
            ))}
            {sources.length > 6 && (
              <span className="text-[11px] text-[var(--text-muted)]">+{sources.length - 6} mas</span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inline document preview (thumbnail + first OCR lines) shown inside the
// ResolvedDocumentCard so the user can see what the file actually looks like
// without leaving the chat.
// ---------------------------------------------------------------------------
function DocumentPreview({ documentId, filename }: { documentId: number; filename: string }) {
  const ext = (filename.split(".").pop() || "").toLowerCase()
  const isImage = ["png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"].includes(ext)
  const thumb = thumbnailUrl(documentId)
  const firstPage = pageImageUrl(documentId, 1)
  const previewSrc = isImage ? thumb : firstPage
  return (
    <div className="mt-2 flex items-stretch gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)]/50 p-2">
      <a
        href={`/documents/${documentId}`}
        className="block flex-shrink-0 overflow-hidden rounded-md border border-[var(--border)] bg-white"
        title="Abrir documento"
        target="_blank"
        rel="noreferrer"
      >
        {/* Use a plain <img> so we don't have to wire the Next/Image pipeline
            for the chat. The backend serves from /api/v1/documents/.../thumbnail
            which is small and cached. */}
        {/* eslint-disable-next-line jsx-a11y/alt-text */}
        <img
          src={previewSrc}
          loading="lazy"
          className="block h-20 w-16 object-cover"
          onError={(e) => {
            // If the thumbnail isn't available, hide the broken image.
            ;(e.currentTarget as HTMLImageElement).style.display = "none"
          }}
        />
      </a>
      <div className="flex min-w-0 flex-1 flex-col justify-center text-[11.5px] leading-snug text-[var(--text-muted)]">
        <span className="mb-0.5 inline-flex items-center gap-1 font-medium uppercase tracking-wide text-[var(--text-secondary)]">
          {isImage ? <ImageIcon className="h-3 w-3" /> : <FileText className="h-3 w-3" />}
          Vista previa · {ext.toUpperCase()}
        </span>
        <a
          href={`/documents/${documentId}`}
          className="truncate font-mono text-[11px] text-[var(--text-secondary)] hover:text-[var(--accent)]"
          title={filename}
        >
          {filename}
        </a>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Follow-up suggestion chips. After each assistant turn the backend returns
// 2-3 short questions; we render them as clickable chips that, when
// clicked, fill the draft textarea so the user can edit / send.
// ---------------------------------------------------------------------------
function FollowupChips({
  followups,
  onPick,
}: {
  followups: string[]
  onPick: (q: string) => void
}) {
  if (!followups || followups.length === 0) return null
  return (
    <div className="mt-2 flex max-w-[88%] flex-wrap gap-1.5 sm:max-w-[80%]">
      {followups.map((q) => (
        <button
          key={q}
          type="button"
          onClick={() => onPick(q)}
          className="group inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--bg-surface)] px-2.5 py-1 text-[11.5px] text-[var(--text-secondary)] transition-colors hover:border-[var(--accent)] hover:bg-[var(--accent-faint)] hover:text-[var(--accent)]"
        >
          <Sparkles className="h-3 w-3 text-[var(--text-muted)] group-hover:text-[var(--accent)]" />
          <span className="line-clamp-1">{q}</span>
          <ArrowRight className="h-3 w-3 opacity-0 transition-opacity group-hover:opacity-100" />
        </button>
      ))}
    </div>
  )
}

function SourceChip({ source }: { source: NonNullable<AIAnswer["sources"]>[number] }) {
  if (!source.document_id) {
    return (
      <span className="inline-flex max-w-[260px] items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-0.5 text-[11px] text-[var(--text-muted)]">
        Doc #{source.document_id ?? "—"}{source.page_number != null && ` · pág. ${source.page_number}`}
      </span>
    )
  }
  return (
    <Link
      to={`/documents/${source.document_id}`}
      className="inline-flex max-w-[260px] items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--bg-surface-2)] px-2 py-0.5 text-[11px] text-[var(--text-secondary)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
      title={source.excerpt ?? ""}
    >
      <ExternalLink className="h-3 w-3 flex-shrink-0" />
      <span className="truncate">Doc #{source.document_id}</span>
      {source.page_number != null && <span>· pág. {source.page_number}</span>}
    </Link>
  )
}

// ---------------------------------------------------------------------------
// ResolvedDocumentCard
// ---------------------------------------------------------------------------
// Rendered above the assistant's prose when the user mentioned a specific
// file. Shows the document's type, status and extracted entities (budget /
// order / invoice / plan) plus a list of related documents with the
// relationship that links them to the main file.
function ResolvedDocumentCard({ resolved }: { resolved: ResolvedDocument }) {
  const doc = resolved.document
  const entities = doc.entities || {}
  const related = resolved.related || []

  // Detect critical missing fields so the user can fix them from the
  // document page. Inline editing is out of scope for the chat; we just
  // surface a "datos incompletos" badge linking to the document.
  const missing: string[] = []
  if (entities.budget) {
    if (!entities.budget.client) missing.push("cliente del presupuesto")
    if (entities.budget.total_amount == null) missing.push("importe del presupuesto")
  }
  if (entities.order && !entities.order.supplier) missing.push("proveedor del pedido")
  if (entities.invoice && entities.invoice.total_amount == null) missing.push("importe de la factura")

  return (
    <div className="mb-3 space-y-2 rounded-xl border border-[var(--accent)]/30 bg-[var(--accent-faint)]/60 p-3 text-[12.5px]">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--accent)]">
            <FileText className="h-3.5 w-3.5" />
            Documento que he analizado
          </div>
          <Link
            to={`/documents/${doc.id}`}
            className="mt-0.5 block truncate text-[13px] font-semibold text-[var(--text-primary)] hover:text-[var(--accent)]"
            title={doc.filename}
          >
            {doc.filename}
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
            {doc.document_type && (
              <Badge variant="neutral" className="capitalize">
                {doc.document_type}
              </Badge>
            )}
            <Badge variant={doc.status === "processed" || doc.status === "processed_ok" ? "success" : "warning"}>
              {doc.status}
            </Badge>
            {doc.confidence != null && <span>OCR {Math.round(doc.confidence * 100)}%</span>}
            {doc.page_count != null && <span>· {doc.page_count} pág.</span>}
            {missing.length > 0 && (
              <Link
                to={`/documents/${doc.id}`}
                className="inline-flex items-center gap-1 rounded border border-[var(--warning)] bg-[var(--warning-faint)] px-1.5 py-0.5 text-[10.5px] font-medium text-[var(--warning)] hover:bg-[var(--warning-light)]"
                title={`Faltan: ${missing.join(", ")}. Pulsa para abrir el documento y completar los datos.`}
              >
                <AlertTriangle className="h-3 w-3" />
                Datos incompletos ({missing.length})
              </Link>
            )}
          </div>
        </div>
      </div>

      {entities.budget && <EntityRow icon={<FileText className="h-3.5 w-3.5" />} label="Presupuesto" e={entities.budget} />}
      {entities.order && <EntityRow icon={<Receipt className="h-3.5 w-3.5" />} label="Pedido" e={entities.order} />}
      {entities.invoice && <EntityRow icon={<Receipt className="h-3.5 w-3.5" />} label="Factura" e={entities.invoice} />}
      {entities.plan && <EntityRow icon={<MapIcon className="h-3.5 w-3.5" />} label="Plano" e={entities.plan} />}

      {doc.vision?.description && (
        <div className="mt-2 rounded-lg border border-[var(--info)]/30 bg-[var(--info-faint)]/60 p-2.5">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--info)]">
            <Sparkles className="h-3.5 w-3.5" />
            Vision aplicada · {doc.vision.model}
          </div>
          <p className="whitespace-pre-wrap text-[12.5px] leading-snug text-[var(--text-primary)]">
            {doc.vision.description}
          </p>
        </div>
      )}

      {related.length > 0 && (
        <div className="mt-1.5 border-t border-[var(--accent)]/20 pt-2">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-[var(--accent)]">
            <Link2 className="h-3.5 w-3.5" />
            Documentos relacionados ({related.length})
          </div>
          <ul className="space-y-1">
            {related.slice(0, 6).map((r) => (
              <li key={r.document_id} className="flex items-start gap-1.5 text-[12px]">
                <span className="mt-0.5 text-[var(--accent)]">↳</span>
                <div className="min-w-0 flex-1">
                  <Link
                    to={`/documents/${r.document_id}`}
                    className="font-medium text-[var(--text-primary)] hover:text-[var(--accent)]"
                  >
                    {r.filename}
                  </Link>
                  <p className="text-[11px] text-[var(--text-muted)]">{r.label}</p>
                </div>
              </li>
            ))}
            {related.length > 6 && (
              <li className="text-[11px] text-[var(--text-muted)]">+{related.length - 6} más</li>
            )}
          </ul>
        </div>
      )}
    </div>
  )
}

function EntityRow({ icon, label, e }: { icon: React.ReactNode; label: string; e: ResolvedDocumentEntity }) {
  const facts: Array<{ k: string; v: string }> = []
  if (e.number) facts.push({ k: "Nº", v: String(e.number) })
  if (e.client) facts.push({ k: "Cliente", v: String(e.client) })
  if (e.supplier) facts.push({ k: "Proveedor", v: String(e.supplier) })
  if (e.total_amount != null) facts.push({ k: "Importe", v: formatMoney(e.total_amount, { currency: e.currency || "EUR" }) })
  if (e.date) facts.push({ k: "Fecha", v: String(e.date) })
  if (e.status) facts.push({ k: "Estado", v: String(e.status) })
  if (e.accepted === true) facts.push({ k: "", v: "aceptado" })
  if (e.accepted === false) facts.push({ k: "", v: "no aceptado" })
  if (e.project_name) facts.push({ k: "Proyecto", v: String(e.project_name) })
  if (e.scale_text) facts.push({ k: "Escala", v: `${e.scale_text}${e.has_valid_scale === false ? " (no válida)" : ""}` })
  if (e.related_budget_id) facts.push({ k: "", v: `vinculado a presupuesto #${e.related_budget_id}` })
  if (e.related_order_id) facts.push({ k: "", v: `vinculado a pedido #${e.related_order_id}` })
  if (typeof e.line_count === "number" && e.line_count > 0) facts.push({ k: "Líneas", v: String(e.line_count) })
  if (!facts.length) return null
  return (
    <div className="mt-1.5 flex items-start gap-1.5">
      <span className="mt-0.5 text-[var(--text-muted)]">{icon}</span>
      <div className="min-w-0 flex-1">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">{label}</span>
        <p className="text-[12.5px] leading-snug text-[var(--text-primary)]">
          {facts.map((f, i) => (
            <span key={i}>
              {f.k && <span className="text-[var(--text-muted)]">{f.k}: </span>}
              <span>{f.v}</span>
              {i < facts.length - 1 ? " · " : ""}
            </span>
          ))}
        </p>
      </div>
    </div>
  )
}

function TypingIndicatorInline() {
  return (
    <div className="flex items-center gap-1.5 py-0.5">
      <Dot delay="0ms" />
      <Dot delay="120ms" />
      <Dot delay="240ms" />
      <span className="ml-1 text-[12px] text-[var(--text-muted)]">pensando…</span>
    </div>
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
