import { useState } from "react"
import {
  AlertTriangle,
  Bot,
  Copy,
  FileSpreadsheet,
  RefreshCw,
  ThumbsDown,
  User as UserIcon,
} from "lucide-react"

import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { AIAnswer } from "@/types/api"

import {
  ActionButton,
  DocumentPreview,
  FollowupChips,
  ResolvedDocumentCard,
  SourceChip,
  TypingIndicatorInline,
} from "./components"
import { renderAssistantContent } from "./renderAssistantContent"
import type { ChatMessage } from "./useChat"

// ---------------------------------------------------------------------------
// MessageBubble
// ---------------------------------------------------------------------------
// Renders one message in the conversation. User messages are right-aligned
// bubbles; assistant messages are left-aligned and (when a full answer is
// available) show the resolved document card, the sources, the rendered
// markdown body, the confidence badge and the action row.
// ---------------------------------------------------------------------------
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
  const VISIBLE_SOURCES = 6
  const visibleSources = showAllSources ? sources : sources.slice(0, VISIBLE_SOURCES)
  const hasMoreSources = sources.length > VISIBLE_SOURCES

  if (isUser) {
    return (
      <div className="flex items-start justify-end gap-3">
        <Card className="max-w-[88%] rounded-2xl rounded-tr-sm border-[var(--accent)]/40 bg-[var(--accent-faint)]/70 px-4 py-2.5 sm:max-w-[80%]">
          <CardContent className="p-0 text-[14px] leading-relaxed text-[var(--text-primary)]">
            {message.content}
          </CardContent>
        </Card>
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-[var(--ink)] text-[var(--bg-base)]">
          <UserIcon className="h-4 w-4" />
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-start gap-3">
      <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-[var(--accent-light)] text-[var(--accent)]">
        <Bot className="h-4 w-4" />
      </div>
      <div className="flex max-w-[88%] flex-col gap-2 sm:max-w-[80%]">
        {resolved && <ResolvedDocumentCard resolved={resolved} />}

        {message.answer?.id && resolved?.document && (
          <DocumentPreview
            documentId={resolved.document.id}
            filename={resolved.document.filename}
          />
        )}

        <div
          className={cn(
            "rounded-2xl rounded-tl-sm border border-[var(--border)] bg-[var(--bg-surface-2)]/60 px-4 py-3",
            isIncorrect && "border-[var(--warning)]/60 bg-[var(--warning-faint)]/40",
          )}
        >
          {message.pending && message.content === "" ? (
            <TypingIndicatorInline />
          ) : message.pending ? (
            <div className="text-[14.5px] leading-relaxed text-[var(--text-primary)]">
              {message.content || (
                <span className="text-[var(--text-muted)]">…</span>
              )}
            </div>
          ) : (
            <>
              {renderAssistantContent(showFullAnswer ? message.content : truncateAnswer(message.content))}
              {message.content.length > 600 && (
                <button
                  type="button"
                  onClick={() => setShowFullAnswer((v) => !v)}
                  className="mt-2 text-[11.5px] font-medium text-[var(--accent)] hover:underline"
                >
                  {showFullAnswer ? "Ver menos" : "Ver respuesta completa"}
                </button>
              )}
            </>
          )}

          {hasAnswer && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              {!sufficient && (
                <span className="inline-flex items-center gap-1 rounded-full border border-[var(--warning)]/40 bg-[var(--warning-faint)] px-2 py-0.5 text-[11px] text-[var(--warning)]">
                  <AlertTriangle className="h-3 w-3" />
                  Sin fuentes
                </span>
              )}
              {message.answer?.confidence != null && (
                <ConfidenceBadge value={message.answer.confidence} />
              )}
              {message.answer?.model_name && (
                <span className="rounded-full border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-0.5 text-[11px] text-[var(--text-muted)]">
                  {message.answer.model_name}
                </span>
              )}
            </div>
          )}

          {sources.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {visibleSources.map((s, i) => (
                <SourceChip key={i} source={s} />
              ))}
              {hasMoreSources && (
                <button
                  type="button"
                  onClick={() => setShowAllSources((v) => !v)}
                  className="rounded-full border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-0.5 text-[11px] text-[var(--text-secondary)] hover:border-[var(--accent)] hover:text-[var(--accent)]"
                >
                  {showAllSources ? "Ver menos" : `+${sources.length - VISIBLE_SOURCES} más`}
                </button>
              )}
            </div>
          )}
        </div>

        {hasAnswer && !message.pending && (
          <FollowupChips followups={message.answer!.followups ?? []} onPick={onPickFollowup} />
        )}

        {hasAnswer && !message.pending && (
          <div className="flex items-center gap-1 text-[var(--text-muted)]">
            <ActionButton onClick={onCopy} title="Copiar respuesta" ariaLabel="Copiar respuesta">
              <Copy className="h-3.5 w-3.5" />
            </ActionButton>
            <ActionButton onClick={onExport} title="Exportar a CSV" ariaLabel="Exportar a CSV">
              <FileSpreadsheet className="h-3.5 w-3.5" />
            </ActionButton>
            <ActionButton onClick={onTask} title="Crear tarea de revisión" ariaLabel="Crear tarea de revisión">
              <AlertTriangle className="h-3.5 w-3.5" />
            </ActionButton>
            <ActionButton onClick={onRegenerate} title="Regenerar respuesta" ariaLabel="Regenerar respuesta">
              <RefreshCw className="h-3.5 w-3.5" />
            </ActionButton>
            <ActionButton
              onClick={onMarkIncorrect}
              title="Marcar como incorrecta"
              ariaLabel="Marcar como incorrecta"
              hoverColor={isIncorrect ? "warning" : "primary"}
            >
              <ThumbsDown className={cn("h-3.5 w-3.5", isIncorrect && "text-[var(--warning)]")} />
            </ActionButton>
          </div>
        )}
      </div>
    </div>
  )
}

function truncateAnswer(text: string): string {
  if (text.length <= 600) return text
  // Cut at the last paragraph or sentence boundary under 600 chars to
  // avoid slicing mid-word. The "Ver respuesta completa" button
  // toggles ``showFullAnswer`` to render the whole thing.
  const slice = text.slice(0, 600)
  const lastBreak = Math.max(slice.lastIndexOf("\n\n"), slice.lastIndexOf(". "))
  if (lastBreak > 200) {
    return slice.slice(0, lastBreak + 1)
  }
  return slice
}

// Export the unused AIAnswer type so it isn't tree-shaken if a
// downstream tool inspects the module.
export type { AIAnswer }
