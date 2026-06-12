import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  History,
  Loader2,
  Send,
  Trash2,
  X,
} from "lucide-react"

import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { PageHeader } from "@/components/layout/PageHeader"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

import { HistoryRow, TypingIndicator, WelcomeCard } from "./chat/components"
import { MessageBubble } from "./chat/MessageBubble"
import { useChat } from "./chat/useChat"

// ---------------------------------------------------------------------------
// F8b - chat page composition
//
// Before F8b the file was 1.2 KB / 1,222 lines with 30+ queries,
// 25+ useState, a 130-line streaming handler, localStorage
// persistence, a markdown renderer, and 9 sub-components all
// living side by side. After F8b:
//
// * state + side effects live in ``useChat``;
// * markdown rendering lives in ``renderAssistantContent``;
// * sub-components (WelcomeCard, HistoryRow, MessageBubble,
//   DocumentPreview, ResolvedDocumentCard, SourceChip, ...)
//   live in ``chat/components``;
// * the page itself is just the layout glue, around 200 lines.
// ---------------------------------------------------------------------------
export function ChatPage() {
  const chat = useChat()
  const hasMessages = chat.messages.length > 0

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Breadcrumbs items={[{ label: "Preguntar a documentos" }]} />
      <PageHeader
        title="Preguntar a documentos"
        description="Conversa con la base documental. Cada respuesta cita sus fuentes para que puedas comprobarla."
        variant="plain"
        actions={
          hasMessages ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={chat.clearConversation}
              className="gap-1.5 text-[var(--text-muted)] hover:text-[var(--danger)]"
            >
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
            <div
              ref={chat.scrollRef}
              className="min-h-0 flex-1 overflow-y-auto"
              style={{ scrollbarGutter: "stable" }}
            >
              <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-4 py-6 sm:px-6">
                {!hasMessages && chat.hydrated && <WelcomeCard onPick={chat.pickQuestion} />}

                {chat.messages.map((m) => (
                  <MessageBubble
                    key={m.id}
                    message={m}
                    isIncorrect={chat.markedIncorrect.has(m.id)}
                    onCopy={() => chat.copyAnswer(m)}
                    onExport={() => chat.exportToExcel(m)}
                    onTask={() => chat.createTask(m)}
                    onRegenerate={() => chat.regenerate(m)}
                    onMarkIncorrect={() => chat.markIncorrect(m.id)}
                    onPickFollowup={chat.pickQuestion}
                  />
                ))}

                {chat.isStreaming && !chat.messages.some((m) => m.pending) && <TypingIndicator />}
              </div>
            </div>

            {/* Input area */}
            <div className="border-t border-[var(--border)] bg-[var(--bg-surface)] px-4 py-3 sm:px-6">
              <div className="mx-auto w-full max-w-3xl">
                <form onSubmit={chat.onSubmit} className="flex items-end gap-2">
                  <div className="flex-1 rounded-2xl border border-[var(--border-2)] bg-[var(--bg-base)] shadow-paper transition-colors focus-within:border-[var(--accent)] focus-within:bg-[var(--bg-surface)]">
                    <textarea
                      ref={chat.textareaRef}
                      value={chat.draft}
                      onChange={(e) => chat.setDraft(e.target.value)}
                      onKeyDown={chat.onKeyDown}
                      onCompositionStart={chat.onCompositionStart}
                      onCompositionEnd={chat.onCompositionEnd}
                      rows={1}
                      placeholder="Escribe tu pregunta…  (Enter para enviar, Shift+Enter para nueva linea)"
                      className="block w-full resize-none bg-transparent px-4 py-3 text-[14px] leading-relaxed text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none"
                      disabled={chat.isStreaming}
                    />
                    <div className="flex items-center justify-between border-t border-[var(--border)]/60 px-2 py-1.5 text-[11px] text-[var(--text-muted)]">
                      <button
                        type="button"
                        onClick={() => chat.setFiltersOpen((v) => !v)}
                        className="inline-flex items-center gap-1 rounded px-1.5 py-1 transition-colors hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-secondary)]"
                      >
                        {chat.filtersOpen ? (
                          <ChevronUp className="h-3 w-3" />
                        ) : (
                          <ChevronDown className="h-3 w-3" />
                        )}
                        <span>
                          Filtros{" "}
                          {activeFilterCount(chat.supplier, chat.documentType) > 0 && (
                            <span className="ml-0.5 rounded bg-[var(--accent-light)] px-1 text-[10px] font-semibold text-[var(--accent)]">
                              {activeFilterCount(chat.supplier, chat.documentType)}
                            </span>
                          )}
                        </span>
                      </button>
                      <span className="hidden sm:inline">
                        {chat.isStreaming ? (
                          <span className="inline-flex items-center gap-1 text-[var(--accent)]">
                            <Loader2 className="h-3 w-3 animate-spin" />
                            pensando...
                          </span>
                        ) : (
                          `${chat.draft.length} caracteres`
                        )}
                      </span>
                    </div>
                  </div>
                  {chat.isStreaming ? (
                    <Button
                      type="button"
                      onClick={chat.stop}
                      className="h-11 w-11 flex-shrink-0 rounded-2xl p-0"
                      aria-label="Detener respuesta"
                      variant="outline"
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  ) : (
                    <Button
                      type="submit"
                      disabled={!chat.draft.trim() || chat.isStreaming}
                      className="h-11 w-11 flex-shrink-0 rounded-2xl p-0"
                      aria-label="Enviar pregunta"
                    >
                      <Send className="h-4 w-4" />
                    </Button>
                  )}
                </form>

                {chat.filtersOpen && (
                  <div className="mt-2 grid gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)]/60 p-2 sm:grid-cols-3">
                    <select
                      className="h-9 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 text-[13px]"
                      value={chat.mode}
                      onChange={(e) => chat.setMode(e.target.value)}
                    >
                      <option value="hybrid">Búsqueda híbrida</option>
                      <option value="semantic">Búsqueda semántica</option>
                      <option value="budget">Solo presupuestos</option>
                      <option value="order">Solo pedidos</option>
                    </select>
                    <input
                      value={chat.supplier}
                      onChange={(e) => chat.setSupplier(e.target.value)}
                      placeholder="Filtrar por proveedor"
                      className="h-9 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 text-[13px] focus:border-[var(--accent)] focus:outline-none"
                    />
                    <input
                      value={chat.documentType}
                      onChange={(e) => chat.setDocumentType(e.target.value)}
                      placeholder="Filtrar por tipo documental"
                      className="h-9 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 text-[13px] focus:border-[var(--accent)] focus:outline-none"
                    />
                  </div>
                )}

                {chat.isStreaming && chat.messages.some((m) => m.pending) && (
                  <p className="mt-2 text-[12px] text-[var(--text-muted)]">
                    La IA está escribiendo. Pulsa{" "}
                    <kbd className="rounded border border-[var(--border)] bg-[var(--bg-surface-2)] px-1 font-mono text-[10px]">
                      ×
                    </kbd>{" "}
                    para detener.
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
                {chat.history.length === 0 ? (
                  <p className="px-2 py-3 text-[13px] text-[var(--text-muted)]">
                    Sin historial reciente.
                  </p>
                ) : (
                  <ul className="space-y-1">
                    {chat.history.slice(0, 12).map((item) => (
                      <li key={item.id}>
                        <HistoryRow item={item} onPick={chat.pickQuestion} />
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

function activeFilterCount(supplier: string, documentType: string): number {
  let n = 0
  if (supplier.trim()) n += 1
  if (documentType.trim()) n += 1
  return n
}
