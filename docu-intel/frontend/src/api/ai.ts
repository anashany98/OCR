import type { AIAnswer, AIQuestion } from "@/types/api"
import { request } from "./core"

export const aiApi = {
  askAI: (question: string, mode?: string) =>
    request<AIAnswer>("/ai/ask", {
      method: "POST",
      body: JSON.stringify({ question, mode }),
    }),
  aiAnswer: (id: number) => request<AIAnswer>(`/ai/answers/` + id),
  aiHistory: () => request<AIQuestion[]>(`/ai/history`),
}
