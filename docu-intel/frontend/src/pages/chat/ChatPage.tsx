import { ChevronDown, ChevronUp, Download, Loader2, Plus, Send, X } from "lucide-react"

import { AutoBreadcrumbs } from "@/components/layout/AutoBreadcrumbs"
import { Button } from "@/components/ui/button"

import { ConversationSidebar, ConversationSidebarMobile } from "./ConversationSidebar"
import { TypingIndicator, WelcomeCard } from "./components"
import { MessageBubble } from "./MessageBubble"
import { useChat } from "./useChat"

export function ChatPage() {
  const chat = useChat()
  const hasMessages = chat.messages.length > 0

  return (
    <div className="flex h-[calc(100vh-3rem)] flex-col gap-3">
      <AutoBreadcrumbs />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-semibold text-[var(--text-primary)]">Chat IA</h1>
          <p className="text-[12px] text-[var(--text-muted)]">
            Pregunta a tus documentos con inteligencia artificial.
          </p>
        </div>
        <div className="flex gap-2">
          {hasMessages && (
            <Button
              variant="outline"
              size="sm"
              onClick={chat.exportConversation}
              className="gap-1.5 text-[11px]"
            >
              <Download className="h-3 w-3" /> Exportar
            </Button>
          )}
          <Button size="sm" onClick={chat.newConversation} className="gap-1.5 text-[11px]">
            <Plus className="h-3 w-3" /> Nueva conversación
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 gap-3">
        {/* Desktop sidebar */}
        <aside className="hidden w-[240px] flex-shrink-0 flex-col rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] lg:flex">
          <ConversationSidebar chat={chat} />
        </aside>

        {/* Mobile sidebar */}
        <ConversationSidebarMobile
          chat={chat}
          open={chat.sidebarOpen}
          onClose={() => chat.setSidebarOpen(false)}
        />

        {/* Main chat area */}
        <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-[var(--border)] bg-[var(--bg-surface)]">
          {/* Mobile menu */}
          <div className="flex items-center border-b border-[var(--border)] px-4 py-2 lg:hidden">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => chat.setSidebarOpen(true)}
              className="gap-1.5 text-[12px]"
            >
              Conversaciones
            </Button>
            {chat.activeConv && (
              <span className="ml-2 truncate text-[11px] text-[var(--text-muted)]">
                {chat.activeConv.title}
              </span>
            )}
          </div>

          {/* Messages */}
          <div
            ref={chat.scrollRef}
            className="min-h-0 flex-1 overflow-y-auto"
            style={{ scrollbarGutter: "stable" }}
          >
            <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-5 sm:px-6">
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

          {/* Composer */}
          <div className="border-t border-[var(--border)] bg-[var(--bg-surface)] px-4 py-3 sm:px-6">
            <div className="mx-auto max-w-3xl">
              <form onSubmit={chat.onSubmit} className="flex items-end gap-2">
                <div className="flex-1 rounded-xl border border-[var(--border-2)] bg-[var(--bg-canvas)] transition-colors focus-within:border-[var(--accent)] focus-within:bg-[var(--bg-surface)] focus-within:shadow-xs">
                  <textarea
                    ref={chat.textareaRef}
                    value={chat.draft}
                    onChange={(e) => chat.setDraft(e.target.value)}
                    onKeyDown={chat.onKeyDown}
                    onCompositionStart={chat.onCompositionStart}
                    onCompositionEnd={chat.onCompositionEnd}
                    rows={1}
                    placeholder="Escribe tu pregunta..."
                    className="block w-full resize-none bg-transparent px-4 py-3 text-[13px] leading-relaxed text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none"
                    disabled={chat.isStreaming}
                  />
                  <div className="flex items-center justify-between border-t border-[var(--border)]/50 px-3 py-1.5">
                    <button
                      type="button"
                      onClick={() => chat.setFiltersOpen((v) => !v)}
                      className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--text-muted)] transition-colors hover:bg-[var(--bg-surface-2)] hover:text-[var(--text-secondary)]"
                    >
                      {chat.filtersOpen ? (
                        <ChevronUp className="h-2.5 w-2.5" />
                      ) : (
                        <ChevronDown className="h-2.5 w-2.5" />
                      )}
                      Filtros
                      {activeFilterCount(chat.supplier, chat.documentType) > 0 && (
                        <span className="ml-0.5 rounded bg-[var(--accent-light)] px-1 text-[9px] font-semibold text-[var(--accent)]">
                          {activeFilterCount(chat.supplier, chat.documentType)}
                        </span>
                      )}
                    </button>
                    <span className="text-[10px] text-[var(--text-muted)]">
                      {chat.isStreaming ? (
                        <span className="inline-flex items-center gap-1 text-[var(--accent)]">
                          <Loader2 className="h-2.5 w-2.5 animate-spin" /> pensando...
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
                    className="h-10 w-10 flex-shrink-0 rounded-xl p-0"
                    variant="outline"
                    aria-label="Detener"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    disabled={!chat.draft.trim() || chat.isStreaming}
                    className="h-10 w-10 flex-shrink-0 rounded-xl p-0"
                    aria-label="Enviar"
                  >
                    <Send className="h-4 w-4" />
                  </Button>
                )}
              </form>

              {chat.filtersOpen && (
                <div className="mt-2 grid gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-surface-2)] p-2 sm:grid-cols-3">
                  <select
                    className="h-8 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 text-[12px] text-[var(--text-primary)]"
                    value={chat.mode}
                    onChange={(e) => chat.setMode(e.target.value)}
                  >
                    <option value="hybrid">Híbrida</option>
                    <option value="semantic">Semántica</option>
                    <option value="budget">Presupuestos</option>
                    <option value="order">Pedidos</option>
                  </select>
                  <input
                    value={chat.supplier}
                    onChange={(e) => chat.setSupplier(e.target.value)}
                    placeholder="Proveedor"
                    className="h-8 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 text-[12px] focus:border-[var(--accent)] focus:outline-none"
                  />
                  <input
                    value={chat.documentType}
                    onChange={(e) => chat.setDocumentType(e.target.value)}
                    placeholder="Tipo documental"
                    className="h-8 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 text-[12px] focus:border-[var(--accent)] focus:outline-none"
                  />
                </div>
              )}

              {chat.isStreaming && chat.messages.some((m) => m.pending) && (
                <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
                  La IA está escribiendo...
                </p>
              )}
            </div>
          </div>
        </div>
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
