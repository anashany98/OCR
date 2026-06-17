import type { AIAnswer, AIQuestion } from "@/types/api"
import { request } from "./core"

export type AIStreamEvent =
  | { type: "start"; model: string }
  | { type: "delta"; text: string }
  | { type: "thinking"; text: string }
  | {
      type: "end"
      answer: string
      answer_id: number
      model: string
      confidence: number | null
      fallback: boolean
      resolved_document: AIAnswer["resolved_document"]
      sources: NonNullable<AIAnswer["sources"]>
      followups: string[]
    }

export const aiApi = {
  askAI: (question: string, mode?: string) =>
    request<AIAnswer>("/ai/ask", {
      method: "POST",
      body: JSON.stringify({ question, mode }),
    }),
  /**
   * Server-Sent Events stream. Yields one `AIStreamEvent` per server event.
   * The connection stays open until the server emits an `end` event.
   */
  askAIStream: async function* (
    question: string,
    mode?: string,
    signal?: AbortSignal,
  ): AsyncGenerator<AIStreamEvent> {
    const base = import.meta.env.VITE_API_BASE_URL || "/api/v1"
    const res = await fetch(`${base}/ai/ask/stream`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question, mode }),
      signal,
    })
    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => res.statusText)
      throw new Error(`Stream failed: ${res.status} ${text}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // Split on SSE event boundary (blank line).
      let boundary: number
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const ev = parseSseEvent(raw)
        if (ev) yield ev
      }
    }
  },
  aiAnswer: (id: number) => request<AIAnswer>(`/ai/answers/` + id),
  aiHistory: () => request<AIQuestion[]>(`/ai/history`),
}

function parseSseEvent(raw: string): AIStreamEvent | null {
  let eventName: string | null = null
  const dataLines: string[] = []
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim()
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim())
    }
  }
  if (!eventName || dataLines.length === 0) return null
  try {
    const payload = JSON.parse(dataLines.join("\n"))
    return { type: eventName, ...payload } as AIStreamEvent
  } catch {
    return null
  }
}
