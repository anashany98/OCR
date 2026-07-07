import { useState } from "react"
import { AlertTriangle, Bot, Copy, FileSpreadsheet, RefreshCw, ThumbsDown, User as UserIcon } from "lucide-react"

import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { cn } from "@/lib/utils"
import type { AIAnswer } from "@/types/api"

import { ActionButton, FollowupChips, ResolvedDocumentCard, TypingIndicatorInline } from "./components"
import { renderAssistantContent } from "./renderAssistantContent"
import { SourceCard } from "./SourceCard"
import type { ChatMessage } from "./useChat"

export function MessageBubble({
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
  const [showAllSources, setShowAllSources] = useState(false)
  const [showFullAnswer, setShowFullAnswer] = useState(false)
  const VISIBLE_SOURCES = 3
  const visibleSources = showAllSources ? sources : sources.slice(0, VISIBLE_SOURCES)
  const hasMoreSources = sources.length > VISIBLE_SOURCES

  if (isUser) {
    const time = new Date(message.createdAt).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })
    return (
      <div className="flex items-end justify-end gap-2">
        <div className="flex flex-col items-end gap-0.5">
          <div className="max-w-[85%] rounded-xl rounded-br-sm bg-[var(--accent)] px-3.5 py-2.5 text-[13px] leading-relaxed text-white sm:max-w-[75%]">
            {message.content}
          </div>
          <span className="text-[9px] text-[var(--text-muted)]">{time}</span>
        </div>
        <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-[var(--accent)]/20 text-[var(--accent)]">
          <UserIcon className="h-3.5 w-3.5" />
        </div>
      </div>
    )
  }

  const time = new Date(message.createdAt).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })

  return (
    <div className="flex items-start gap-2">
      <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-[var(--bg-surface-2)] text-[var(--text-muted)]">
        <Bot className="h-3.5 w-3.5" />
      </div>
      <div className="flex max-w-[85%] flex-col gap-2 sm:max-w-[75%]">
        {resolved && <ResolvedDocumentCard resolved={resolved} />}

        {/* Main answer bubble */}
        <div
          className={cn(
            "rounded-xl rounded-tl-sm border border-[var(--border)] bg-[var(--bg-surface-2)]/50 px-3.5 py-2.5",
            isIncorrect && "border-[var(--warning)]/60 bg-[var(--warning-faint)]/40",
          )}
        >
          {message.pending && message.content === "" ? (
            <TypingIndicatorInline />
          ) : message.pending ? (
            <div className="text-[13px] leading-relaxed text-[var(--text-primary)]">
              {message.content}
              <span className="inline-block h-4 w-0.5 animate-pulse bg-[var(--accent)] ml-0.5 align-text-bottom" />
            </div>
          ) : (
            <>
              {renderAssistantContent(showFullAnswer ? message.content : truncateAnswer(message.content))}
              {message.content.length > 600 && (
                <button
                  type="button"
                  onClick={() => setShowFullAnswer((v) => !v)}
                  className="mt-2 text-[11px] font-medium text-[var(--accent)] hover:underline"
                >
                  {showFullAnswer ? "Ver menos" : "Ver respuesta completa"}
                </button>
              )}
            </>
          )}

          {/* Meta badges */}
          {hasAnswer && (
            <div className="mt-2 flex flex-wrap items-center gap-1">
              {!sufficient && (
                <span className="inline-flex items-center gap-1 rounded-full border border-[var(--warning)]/40 bg-[var(--warning-faint)] px-2 py-0.5 text-[10px] text-[var(--warning)]">
                  <AlertTriangle className="h-2.5 w-2.5" /> Sin fuentes
                </span>
              )}
              {message.answer?.confidence != null && <ConfidenceBadge value={message.answer.confidence} />}
              {message.answer?.model_name && (
                <span className="rounded-full border border-[var(--border)] bg-[var(--bg-surface)] px-1.5 py-0.5 text-[9px] text-[var(--text-muted)]">
                  {message.answer.model_name}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Source cards with preview */}
        {sources.length > 0 && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-medium text-[var(--text-muted)]">
                {sources.length} {sources.length === 1 ? "fuente" : "fuentes"}
              </span>
              {hasMoreSources && (
                <button
                  type="button"
                  onClick={() => setShowAllSources((v) => !v)}
                  className="text-[10px] text-[var(--accent)] hover:underline"
                >
                  {showAllSources ? "Ver menos" : `Ver todas (+${sources.length - VISIBLE_SOURCES})`}
                </button>
              )}
            </div>
            <div className="grid gap-1.5 sm:grid-cols-2">
              {visibleSources.map((s, i) => (
                <SourceCard
                  key={i}
                  documentId={s.document_id ?? 0}
                  filename={s.excerpt?.slice(0, 60) ?? `Documento #${s.document_id}`}
                  pageNumber={s.page_number ?? undefined}
                  confidence={s.relevance_score ?? undefined}
                  excerpt={s.excerpt ?? undefined}
                />
              ))}
            </div>
          </div>
        )}

        {/* Follow-ups */}
        {hasAnswer && !message.pending && message.answer?.followups && message.answer.followups.length > 0 && (
          <FollowupChips followups={message.answer.followups} onPick={onPickFollowup} />
        )}

        {/* Action buttons */}
        {hasAnswer && !message.pending && (
          <div className="flex items-center gap-0.5">
            <ActionButton onClick={onCopy} title="Copiar" ariaLabel="Copiar respuesta">
              <Copy className="h-3 w-3" />
            </ActionButton>
            <ActionButton onClick={onExport} title="Exportar CSV" ariaLabel="Exportar a CSV">
              <FileSpreadsheet className="h-3 w-3" />
            </ActionButton>
            <ActionButton onClick={onTask} title="Crear tarea" ariaLabel="Crear tarea de revisión">
              <AlertTriangle className="h-3 w-3" />
            </ActionButton>
            <ActionButton onClick={onRegenerate} title="Regenerar" ariaLabel="Regenerar respuesta">
              <RefreshCw className="h-3 w-3" />
            </ActionButton>
            <ActionButton
              onClick={onMarkIncorrect}
              title="Incorrecta"
              ariaLabel="Marcar como incorrecta"
              hoverColor={isIncorrect ? "warning" : "primary"}
            >
              <ThumbsDown className={cn("h-3 w-3", isIncorrect && "text-[var(--warning)]")} />
            </ActionButton>
          </div>
        )}
        <span className="text-[9px] text-[var(--text-muted)]">{time}</span>
      </div>
    </div>
  )
}

function truncateAnswer(text: string): string {
  if (text.length <= 600) return text
  const slice = text.slice(0, 600)
  const lastBreak = Math.max(slice.lastIndexOf("\n\n"), slice.lastIndexOf(". "))
  if (lastBreak > 200) return slice.slice(0, lastBreak + 1)
  return slice
}

export type { AIAnswer }
