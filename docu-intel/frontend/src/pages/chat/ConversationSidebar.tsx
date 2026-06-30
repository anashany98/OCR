import { useState } from "react"
import {
  AlertTriangle,
  History,
  Pin,
  PinOff,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { Chat } from "./useChat"

function formatDate(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return "ahora"
  if (diffMins < 60) return `${diffMins}m`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h`
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 7) return `${diffDays}d`
  return d.toLocaleDateString("es-ES", { day: "numeric", month: "short" })
}

export function ConversationSidebar({ chat }: { chat: Chat }) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-2 text-[13px] font-semibold">
          <History className="h-4 w-4 text-[var(--text-muted)]" />
          <span>Conversaciones</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={chat.newConversation}
          className="h-7 gap-1 px-2 text-[12px]"
        >
          <Plus className="h-3.5 w-3.5" />
          Nueva
        </Button>
      </div>

      {/* Search */}
      <div className="border-b border-[var(--border)] px-3 py-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            type="text"
            value={chat.searchQuery}
            onChange={(e) => chat.setSearchQuery(e.target.value)}
            placeholder="Buscar..."
            className="h-8 w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] pl-7 pr-2 text-[12px] placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] focus:outline-none"
          />
          {chat.searchQuery && (
            <button
              type="button"
              onClick={() => chat.setSearchQuery("")}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5 text-[var(--text-muted)] hover:text-[var(--text-primary)]"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Conversation list */}
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {chat.conversations.length === 0 ? (
          <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
            <History className="h-8 w-8 text-[var(--text-muted)]/40" />
            <p className="text-[12px] text-[var(--text-muted)]">
              {chat.searchQuery ? "Sin resultados" : "Sin conversaciones aún"}
            </p>
          </div>
        ) : (
          <ul className="space-y-0.5">
            {chat.conversations.map((conv) => {
              const isActive = conv.id === chat.activeConvId
              const isHovered = conv.id === hoveredId
              const msgCount = conv.messages.length
              const lastMsg = conv.messages[conv.messages.length - 1]
              const preview = lastMsg
                ? lastMsg.role === "user"
                  ? lastMsg.content
                  : lastMsg.content.slice(0, 80) + (lastMsg.content.length > 80 ? "…" : "")
                : ""

              return (
                <li
                  key={conv.id}
                  onMouseEnter={() => setHoveredId(conv.id)}
                  onMouseLeave={() => setHoveredId(null)}
                >
                  <button
                    type="button"
                    onClick={() => chat.switchConversation(conv.id)}
                    className={cn(
                      "group flex w-full flex-col gap-0.5 rounded-lg px-3 py-2.5 text-left transition-colors",
                      isActive
                        ? "bg-[var(--accent-faint)] border border-[var(--accent)]/30"
                        : "border border-transparent hover:bg-[var(--bg-surface-2)]",
                    )}
                  >
                    <div className="flex items-start justify-between gap-1.5">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          {conv.pinned && (
                            <Pin className="h-3 w-3 flex-shrink-0 text-[var(--accent)]" />
                          )}
                          <span
                            className={cn(
                              "line-clamp-1 text-[12.5px]",
                              isActive
                                ? "font-medium text-[var(--text-primary)]"
                                : "text-[var(--text-secondary)]",
                            )}
                          >
                            {conv.title}
                          </span>
                        </div>
                        {preview && (
                          <p className="mt-0.5 line-clamp-1 text-[11px] text-[var(--text-muted)]">
                            {preview}
                          </p>
                        )}
                      </div>
                      <div className="flex flex-col items-end gap-0.5">
                        <span className="text-[10px] text-[var(--text-muted)]">
                          {formatDate(conv.updatedAt)}
                        </span>
                        {isHovered && (
                          <div className="flex items-center gap-0.5">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                chat.togglePin(conv.id)
                              }}
                              className="rounded p-0.5 text-[var(--text-muted)] hover:text-[var(--accent)]"
                              title={conv.pinned ? "Desanclar" : "Anclar"}
                            >
                              {conv.pinned ? (
                                <PinOff className="h-3 w-3" />
                              ) : (
                                <Pin className="h-3 w-3" />
                              )}
                            </button>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                if (confirm("¿Eliminar esta conversación?")) {
                                  chat.deleteConversation(conv.id)
                                }
                              }}
                              className="rounded p-0.5 text-[var(--text-muted)] hover:text-[var(--danger)]"
                              title="Eliminar"
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                    {msgCount > 0 && (
                      <span className="text-[10px] text-[var(--text-muted)]">
                        {msgCount} mensaje{msgCount !== 1 ? "s" : ""}
                      </span>
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {/* Footer info */}
      <div className="border-t border-[var(--border)] px-4 py-2.5">
        <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
          <AlertTriangle className="h-3 w-3" />
          <span>La IA solo usa datos de los documentos.</span>
        </div>
      </div>
    </div>
  )
}

export function ConversationSidebarMobile({
  chat,
  open,
  onClose,
}: {
  chat: Chat
  open: boolean
  onClose: () => void
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex lg:hidden">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative flex h-full w-72 flex-col border-r border-[var(--border)] bg-[var(--bg-base)]">
        <ConversationSidebar chat={chat} />
      </div>
    </div>
  )
}
