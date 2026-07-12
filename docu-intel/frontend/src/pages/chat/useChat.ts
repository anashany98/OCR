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

const CONVERSATIONS_KEY = "docu-intel:chat:conversations"
const ACTIVE_CONV_KEY = "docu-intel:chat:active-conv"
const SESSION_KEY = "docu-intel:chat:session-id"

export type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  createdAt: string
  question?: string
  answer?: AIAnswer
  pending?: boolean
}

export type Conversation = {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: string
  updatedAt: string
  pinned?: boolean
}

// F8-05: metadata-only type for localStorage persistence
type ConversationMetadata = Omit<Conversation, "messages"> & { messageCount: number }

function generateId(): string {
  return typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `conv-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function getActiveSessionId(): string {
  let value = localStorage.getItem(SESSION_KEY)
  if (!value) {
    value = generateId()
    localStorage.setItem(SESSION_KEY, value)
  }
  return value
}

function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(CONVERSATIONS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        // Local storage deliberately holds metadata only. Rehydrate a safe
        // empty message array until server-side history is requested.
        return parsed.map((conversation) => ({ ...conversation, messages: [] }))
      }
    }
  } catch { /* ignore */ }
  return []
}

function saveConversations(convs: Conversation[]) {
  try {
    // F8-05: only persist metadata, not message content
    const metadata: ConversationMetadata[] = convs.map(({ messages, ...rest }) => ({
      ...rest,
      messageCount: messages.length,
    }))
    localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(metadata))
  } catch { /* quota / private mode */ }
}

function extractTitle(messages: ChatMessage[]): string {
  const firstUser = messages.find((m) => m.role === "user")
  if (!firstUser) return "Nueva conversación"
  const text = firstUser.content
  return text.length > 60 ? text.slice(0, 57) + "…" : text
}

export function useChat() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [hydrated, setHydrated] = useState(false)
  const [draft, setDraft] = useState("")
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [mode, setMode] = useState("hybrid")
  const [supplier, setSupplier] = useState("")
  const [documentType, setDocumentType] = useState("")
  const [markedIncorrect, setMarkedIncorrect] = useState<Set<string>>(new Set())
  const [isStreaming, setIsStreaming] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const streamControllerRef = useRef<AbortController | null>(null)
  const isComposingRef = useRef(false)

  const history = useAiHistory()
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Load conversations from localStorage on mount.
  useEffect(() => {
    const loaded = loadConversations()
    setConversations(loaded)
    const savedActive = localStorage.getItem(ACTIVE_CONV_KEY)
    if (savedActive && loaded.some((c) => c.id === savedActive)) {
      setActiveConvId(savedActive)
    } else if (loaded.length > 0) {
      setActiveConvId(loaded[0].id)
    }
    setHydrated(true)
  }, [])

  // Persist conversations.
  useEffect(() => {
    if (!hydrated) return
    saveConversations(conversations)
  }, [conversations, hydrated])

  // Persist active conversation id.
  useEffect(() => {
    if (activeConvId) localStorage.setItem(ACTIVE_CONV_KEY, activeConvId)
  }, [activeConvId])

  // Active conversation.
  const activeConv = conversations.find((c) => c.id === activeConvId) ?? null
  const messages = activeConv?.messages ?? []

  // Auto-scroll.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: isStreaming ? "smooth" : "auto" })
  }, [messages, isStreaming])

  // Auto-resize textarea.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = Math.min(el.scrollHeight, 180) + "px"
  }, [draft])

  // Update a conversation's messages.
  const updateConvMessages = useCallback(
    (convId: string, updater: (msgs: ChatMessage[]) => ChatMessage[]) => {
      setConversations((prev) =>
        prev.map((c) => {
          if (c.id !== convId) return c
          const nextMsgs = updater(c.messages)
          return {
            ...c,
            messages: nextMsgs,
            title: c.messages.length === 0 ? extractTitle(nextMsgs) : c.title,
            updatedAt: new Date().toISOString(),
          }
        }),
      )
    },
    [],
  )

  // Create a new conversation.
  const newConversation = useCallback(() => {
    const id = generateId()
    const conv: Conversation = {
      id,
      title: "Nueva conversación",
      messages: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
    setConversations((prev) => [conv, ...prev])
    setActiveConvId(id)
    setSidebarOpen(false)
    textareaRef.current?.focus()
  }, [])

  // Switch conversation.
  const switchConversation = useCallback((convId: string) => {
    setActiveConvId(convId)
    setSidebarOpen(false)
    setMarkedIncorrect(new Set())
  }, [])

  // Delete conversation.
  const deleteConversation = useCallback(
    (convId: string) => {
      setConversations((prev) => {
        const next = prev.filter((c) => c.id !== convId)
        if (activeConvId === convId) {
          setActiveConvId(next.length > 0 ? next[0].id : null)
        }
        return next
      })
    },
    [activeConvId],
  )

  // Pin/unpin conversation.
  const togglePin = useCallback((convId: string) => {
    setConversations((prev) =>
      prev.map((c) => (c.id === convId ? { ...c, pinned: !c.pinned } : c)),
    )
  }, [])

  // Filtered conversations for search.
  const filteredConversations = searchQuery.trim()
    ? conversations.filter(
        (c) =>
          c.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
          c.messages.some((m) =>
            m.content.toLowerCase().includes(searchQuery.toLowerCase()),
          ),
      )
    : conversations

  // Sorted: pinned first, then by updatedAt.
  const sortedConversations = [...filteredConversations].sort((a, b) => {
    if (a.pinned && !b.pinned) return -1
    if (!a.pinned && b.pinned) return 1
    return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
  })

  // Send message via streaming.
  const sendStream = useCallback(
    async (value: string) => {
      const trimmed = value.trim()
      if (!trimmed || isStreaming) return

      // Ensure there's an active conversation.
      let convId = activeConvId
      if (!convId || !conversations.some((c) => c.id === convId)) {
        const id = generateId()
        const conv: Conversation = {
          id,
          title: extractTitle([{ id: "tmp", role: "user", content: trimmed, createdAt: new Date().toISOString() }]),
          messages: [],
          createdAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
        }
        setConversations((prev) => [conv, ...prev])
        setActiveConvId(id)
        convId = id
      }

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

      updateConvMessages(convId, (prev) => [...prev, userMsg, pendingMsg])
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
          convId,
          controller.signal,
        )) {
          if (ev.type === "thinking") {
            thinkingPieces += 1
            if (thinkingPieces === 1) {
              updateConvMessages(convId, (prev) => {
                const idx = prev.findIndex((m) => m.id === pendingId)
                if (idx === -1) return prev
                const next = [...prev]
                next[idx] = { ...next[idx], content: "razonando…" }
                return next
              })
            }
          } else if (ev.type === "delta") {
            assembled += ev.text
            updateConvMessages(convId, (prev) => {
              const idx = prev.findIndex((m) => m.id === pendingId)
              if (idx === -1) return prev
              const next = [...prev]
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
        updateConvMessages(convId, (prev) => {
          const idx = prev.findIndex((m) => m.id === pendingId)
          if (idx === -1) return prev
          const next = [...prev]
          next[idx] = {
            ...next[idx],
            content:
              assembled ||
              "Lo siento, no he podido completar la busqueda. Revisa tu conexion o intentalo de nuevo.",
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

      updateConvMessages(convId, (prev) => {
        const idx = prev.findIndex((m) => m.id === pendingId)
        if (idx === -1) return prev
        const next = [...prev]
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
        notify.info("Usando fallback estructurado", "El LLM no respondio.")
      } else if (confidence != null && confidence < 0.5) {
        notify.warning("Respuesta con baja confianza", "Verifica las fuentes.")
      }
    },
    [activeConvId, conversations, history, isStreaming, mode, supplier, documentType, updateConvMessages],
  )

  const stop = useCallback(() => {
    streamControllerRef.current?.abort()
  }, [])

  const clearConversation = useCallback(() => {
    if (!activeConvId) return
    updateConvMessages(activeConvId, () => [])
    setMarkedIncorrect(new Set())
  }, [activeConvId, updateConvMessages])

  const copyAnswer = useCallback((message: ChatMessage) => {
    if (!message.answer) return
    navigator.clipboard.writeText(message.answer.answer).catch(() => {})
    notify.success("Respuesta copiada")
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

  const exportConversation = useCallback(() => {
    if (!activeConv) return
    const lines: string[] = [`# ${activeConv.title}`, `_${new Date(activeConv.createdAt).toLocaleString()}_`, ""]
    for (const m of activeConv.messages) {
      if (m.role === "user") {
        lines.push(`**Tú:** ${m.content}`, "")
      } else if (m.answer) {
        lines.push(`**IA:** ${m.answer.answer}`, "")
        if (m.answer.sources.length > 0) {
          lines.push(
            `_Fuentes: ${m.answer.sources.map((s) => `Doc #${s.document_id ?? "?"}`).join(", ")}_`,
            "",
          )
        }
      }
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = `docu-intel-chat-${activeConv.id.slice(0, 8)}.md`
    link.click()
    URL.revokeObjectURL(url)
    notify.success("Conversación exportada")
  }, [activeConv])

  const createTask = useCallback(
    (message: ChatMessage) => {
      if (!message.answer) return
      const question = (message.question || "").trim() || "Pregunta IA"
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
            `Pregunta: ${question}`,
            "",
            "Respuesta:",
            truncatedProse,
            "",
            `Fuentes: ${message.answer.sources.length}`,
            `Confianza: ${message.answer.confidence != null ? Math.round(message.answer.confidence * 100) + "%" : "n/d"}`,
            `Modelo: ${message.answer.model_name ?? "n/d"}`,
          ].join("\n"),
          priority: "normal",
        })
        .then(() => {
          history.refetch()
          notify.success("Tarea creada")
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
      notify.info("Regenerando respuesta")
      if (activeConvId) {
        updateConvMessages(activeConvId, (prev) => prev.filter((m) => m.id !== assistantMessage.id))
      }
      setDraft("")
      void sendStream(question)
    },
    [isStreaming, sendStream, activeConvId, updateConvMessages],
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
    // conversations
    conversations: sortedConversations,
    activeConv,
    activeConvId,
    messages,
    hydrated,
    // draft
    draft,
    setDraft,
    // filters
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
    // sidebar
    sidebarOpen,
    setSidebarOpen,
    searchQuery,
    setSearchQuery,
    // refs
    scrollRef,
    textareaRef,
    // actions
    sendStream,
    stop,
    clearConversation,
    copyAnswer,
    exportToExcel,
    exportConversation,
    createTask,
    regenerate,
    markIncorrect,
    pickQuestion,
    onSubmit,
    onKeyDown,
    onCompositionStart,
    onCompositionEnd,
    // conversation management
    newConversation,
    switchConversation,
    deleteConversation,
    togglePin,
    // queries
    history: history.data ?? ([] as AIQuestion[]),
  }
}

export type Chat = ReturnType<typeof useChat>
