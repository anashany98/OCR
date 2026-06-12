import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react"

import { api } from "@/api/client"
import { useAiHistory } from "@/hooks/useAiHistory"
import { notify } from "@/lib/toast"
import type { AIAnswer, AIQuestion } from "@/types/api"

import { composeQuestion } from "./composeQuestion"

const STORAGE_KEY = "docu-intel:chat:messages"

export type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  createdAt: string
  question?: string
  answer?: AIAnswer
  pending?: boolean
}

/**
 * F8b - chat state hook.
 *
 * Owns the local-only state for the chat: the message list, the
 * draft, the filter inputs, the streaming state and the
 * ``AbortController`` for an in-flight request. The hook
 * persists the message list to ``localStorage`` and rehydrates
 * it on mount; the persistence is debounced to the
 * ``useEffect`` reruns on every ``setMessages``.
 *
 * ``useChat`` is a thin shell over the previous in-component
 * logic. The goal of F8b is to make that logic testable in
 * isolation: the hook accepts the only side-effect
 * (``api.askAIStream``) through a default parameter that
 * tests can override, and it returns a small object with
 * every imperative action the UI used to wire up inline.
 */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [hydrated, setHydrated] = useState(false)
  const [draft, setDraft] = useState("")
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [mode, setMode] = useState("hybrid")
  const [supplier, setSupplier] = useState("")
  const [documentType, setDocumentType] = useState("")
  const [markedIncorrect, setMarkedIncorrect] = useState<Set<string>>(new Set())
  const [isStreaming, setIsStreaming] = useState(false)
  const streamControllerRef = useRef<AbortController | null>(null)
  const isComposingRef = useRef(false)

  const history = useAiHistory()
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

  // Auto-scroll to bottom whenever messages change or a new
  // pending message appears.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: isStreaming ? "smooth" : "auto" })
  }, [messages, isStreaming])

  // Auto-resize the textarea up to a max height.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = Math.min(el.scrollHeight, 180) + "px"
  }, [draft])

  const sendStream = useCallback(
    async (value: string) => {
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
            // Reasoning models (Qwen3) emit "thinking" tokens
            // before the final answer. We count them and use
            // that to flip the UI from "pensando" to
            // "razonando..." so the user knows the model is
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
            content:
              assembled ||
              "Lo siento, no he podido completar la busqueda. Revisa tu conexion o intentalo de nuevo en unos segundos.",
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

      // Finalise the assistant message: replace the pending
      // placeholder with a fully-populated AIAnswer so the
      // card / followups / etc. render.
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
        notify.info(
          "Usando fallback estructurado",
          "El LLM no respondio; mostramos el resumen grounded.",
        )
      } else if (confidence != null && confidence < 0.5) {
        notify.warning(
          "Respuesta con baja confianza",
          "La IA no encontró evidencia sólida. Verifica las fuentes.",
        )
      }
    },
    [history, isStreaming, mode, supplier, documentType],
  )

  const stop = useCallback(() => {
    streamControllerRef.current?.abort()
  }, [])

  const clearConversation = useCallback(() => {
    if (!messages.length) return
    if (!confirm("¿Borrar toda la conversacion?")) return
    setMessages([])
    setMarkedIncorrect(new Set())
    try {
      localStorage.removeItem(STORAGE_KEY)
    } catch {
      // private mode — non-fatal
    }
  }, [messages.length])

  const copyAnswer = useCallback((message: ChatMessage) => {
    if (!message.answer) return
    navigator.clipboard.writeText(message.answer.answer).catch(() => {})
    notify.success("Respuesta copiada al portapapeles")
  }, [])

  const exportToExcel = useCallback((message: ChatMessage) => {
    if (!message.answer) return
    const a = message.answer
    const rows: string[][] = [["Pregunta", "Respuesta", "Confianza", "Fuentes", "Modelo", "Fecha"]]
    const sources = a.sources
      .map((s) => `Doc #${s.document_id ?? "-"} Pág.${s.page_number ?? "-"}: ${s.excerpt ?? "-"}`)
      .join(" | ")
    rows.push([
      message.content,
      a.answer,
      a.confidence != null ? `${Math.round(a.confidence * 100)}%` : "-",
      sources,
      a.model_name ?? "-",
      a.created_at,
    ])
    const csv = rows
      .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","))
      .join("\n")
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = `docu-intel-respuesta-${a.id}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }, [])

  const createTask = useCallback(
    (message: ChatMessage) => {
      if (!message.answer) return
      const question = (message.question || "").trim() || "Pregunta IA"
      // Extract only the conversational "Respuesta:" prose for
      // the description, not the whole structured audit block.
      const respuestaMatch = message.answer.answer.match(
        /\*\*Respuesta:\*\*\s*([\s\S]*?)(?=\n\n\*\*|$)/,
      )
      const respuestaProse = (respuestaMatch ? respuestaMatch[1] : message.answer.answer).trim()
      const truncatedProse =
        respuestaProse.length > 500 ? respuestaProse.slice(0, 500) + "…" : respuestaProse
      api
        .createWorkItem({
          kind: "manual",
          title: `Revisar respuesta IA: ${question.slice(0, 80)}`,
          description: [
            `Pregunta del usuario: ${question}`,
            "",
            "Respuesta de la IA:",
            truncatedProse,
            "",
            `Fuentes citadas: ${message.answer.sources.length}`,
            `Confianza: ${
              message.answer.confidence != null
                ? Math.round(message.answer.confidence * 100) + "%"
                : "n/d"
            }`,
            `Modelo: ${message.answer.model_name ?? "n/d"}`,
          ].join("\n"),
          priority: "normal",
        })
        .then(() => {
          history.refetch()
          notify.success("Tarea creada para revisar la respuesta")
        })
        .catch((err) => notify.error(err, "No se pudo crear la tarea"))
    },
    [history],
  )

  const regenerate = useCallback(
    (assistantMessage: ChatMessage) => {
      if (isStreaming) return
      const question = (assistantMessage.question || "").trim()
      if (!question) return
      notify.info("Regenerando respuesta", "Volviendo a lanzar la consulta al modelo.")
      setMessages((current) => current.filter((m) => m.id !== assistantMessage.id))
      setDraft("")
      void sendStream(question)
    },
    [isStreaming, sendStream],
  )

  const markIncorrect = useCallback((id: string) => {
    setMarkedIncorrect((prev) => new Set(prev).add(id))
  }, [])

  const onSubmit = useCallback(
    (event: FormEvent) => {
      event.preventDefault()
      void sendStream(draft)
    },
    [draft, sendStream],
  )

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key === "Enter" && !event.shiftKey && !isComposingRef.current) {
        event.preventDefault()
        void sendStream(draft)
      }
    },
    [draft, sendStream],
  )

  const onCompositionStart = useCallback(() => {
    isComposingRef.current = true
  }, [])
  const onCompositionEnd = useCallback(() => {
    isComposingRef.current = false
  }, [])

  const pickQuestion = useCallback((q: string) => {
    setDraft(q)
    textareaRef.current?.focus()
  }, [])

  return {
    // state
    messages,
    hydrated,
    draft,
    setDraft,
    filtersOpen,
    setFiltersOpen,
    mode,
    setMode,
    supplier,
    setSupplier,
    documentType,
    setDocumentType,
    markedIncorrect,
    isStreaming,
    // refs (must be forwarded to the underlying DOM)
    scrollRef,
    textareaRef,
    // imperative actions
    sendStream,
    stop,
    clearConversation,
    copyAnswer,
    exportToExcel,
    createTask,
    regenerate,
    markIncorrect,
    pickQuestion,
    onSubmit,
    onKeyDown,
    onCompositionStart,
    onCompositionEnd,
    // queries
    history: history.data ?? ([] as AIQuestion[]),
  }
}

export type Chat = ReturnType<typeof useChat>
