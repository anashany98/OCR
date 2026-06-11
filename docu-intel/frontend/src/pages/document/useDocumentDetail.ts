import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"
import type {
  DocumentEntity,
  DocumentGraph,
  DocumentPage,
  DocumentTimelineEvent,
} from "@/types/api"

// ---------------------------------------------------------------------------
// F8b-cont2 - document detail hook
// ---------------------------------------------------------------------------
// Owns every piece of state the document detail page needs: the
// document / pages / blocks / entities / timeline / graph queries,
// the selected page, the OCR text search, the revision draft, the
// reprocess mutation, the save-revision mutation and the helper
// "invalidate everything" used after a write.
// ---------------------------------------------------------------------------

const KEY_ENTITIES = new Set([
  "invoice_number", "budget_number", "order_number",
  "supplier", "supplier_name", "client", "client_name",
  "total_amount", "amount", "amount_total",
  "date", "invoice_date", "budget_date", "order_date",
  "currency", "reference",
])

const ENTITY_LABELS: Record<string, string> = {
  invoice_number: "Nº Factura",
  budget_number: "Nº Presupuesto",
  order_number: "Nº Pedido",
  supplier: "Proveedor",
  supplier_name: "Proveedor",
  client: "Cliente",
  client_name: "Cliente",
  total_amount: "Importe total",
  amount: "Importe",
  amount_total: "Importe total",
  date: "Fecha",
  invoice_date: "Fecha factura",
  budget_date: "Fecha presupuesto",
  order_date: "Fecha pedido",
  currency: "Moneda",
  reference: "Referencia",
}

export function isKeyEntity(entityType: string): boolean {
  return KEY_ENTITIES.has(entityType) || KEY_ENTITIES.has(entityType.toLowerCase())
}

export function entityLabel(entityType: string): string {
  return ENTITY_LABELS[entityType] ?? entityType.replace(/_/g, " ")
}

/** Filter pages by case-insensitive substring on the OCR text. */
export function filterPages(pages: DocumentPage[], query: string): DocumentPage[] {
  const q = query.trim().toLowerCase()
  if (!q) return pages
  return pages.filter((p) => (p.text ?? "").toLowerCase().includes(q))
}

/** Build the short file-hash display: first 10 + "..." + last 6. */
export function shortHash(hash: string | null | undefined): string {
  if (!hash) return "—"
  return `${hash.slice(0, 10)}...${hash.slice(-6)}`
}

/** Supported image extensions for thumbnail fallback. */
export function hasThumbnailExt(extension: string | null | undefined): boolean {
  if (!extension) return false
  return [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"].includes(
    extension.toLowerCase(),
  )
}

export function useDocumentDetail(documentId: number) {
  const queryClient = useQueryClient()
  const valid = Number.isFinite(documentId)

  // R4 — Scroll to cited block when navigating from AI chat sources.
  // The URL hash is #page=N&block=M (set by the chat source link).
  useEffect(() => {
    const hash = window.location.hash
    if (!hash) return
    const params = new URLSearchParams(hash.slice(1))
    const blockId = params.get("block")
    if (!blockId) return
    // Wait for the blocks table to render, then scroll to the cited block.
    const timer = setTimeout(() => {
      const el = document.querySelector(`[data-block-id="${blockId}"]`)
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" })
        el.classList.add("ring-2", "ring-amber-400", "bg-amber-50")
        setTimeout(() => {
          el.classList.remove("ring-2", "ring-amber-400", "bg-amber-50")
        }, 3000)
      }
    }, 500)
    return () => clearTimeout(timer)
  }, [])

  // Local UI state
  const [selectedPageNumber, setSelectedPageNumber] = useState<number | null>(null)
  const [textQuery, setTextQuery] = useState("")
  const [editedText, setEditedText] = useState("")
  const [revisionReason, setRevisionReason] = useState("")
  const [showGraph, setShowGraph] = useState(false)
  const [showBlocks, setShowBlocks] = useState(false)

  // Queries
  const docQ = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => api.document(documentId),
    enabled: valid,
  })
  const pagesQ = useQuery({
    queryKey: ["document-pages", documentId],
    queryFn: () => api.pages(documentId),
    enabled: valid,
  })
  const blocksQ = useQuery({
    queryKey: ["document-blocks", documentId],
    queryFn: () => api.blocks(documentId),
    enabled: valid,
  })
  const entitiesQ = useQuery({
    queryKey: ["document-entities", documentId],
    queryFn: () => api.entities(documentId),
    enabled: valid,
  })
  const timelineQ = useQuery({
    queryKey: ["document-timeline", documentId],
    queryFn: () => api.documentTimeline(documentId),
    enabled: valid,
  })
  const graphQ = useQuery({
    queryKey: ["document-graph", documentId],
    queryFn: () => api.documentGraph(documentId),
    enabled: showGraph && valid,
  })

  const doc = docQ.data
  const pages = pagesQ.data ?? []
  const entities = entitiesQ.data ?? []

  const selectedPage = useMemo<DocumentPage | undefined>(() => {
    if (!pages.length) return undefined
    return pages.find((p) => p.page_number === selectedPageNumber) ?? pages[0]
  }, [pages, selectedPageNumber])

  const revisionsQ = useQuery({
    queryKey: ["ocr-revisions", selectedPage?.id],
    queryFn: () => api.ocrRevisions(selectedPage!.id),
    enabled: Boolean(selectedPage),
  })

  const visiblePages = useMemo(() => filterPages(pages, textQuery), [pages, textQuery])
  const keyEnts = useMemo(() => entities.filter((e) => isKeyEntity(e.entity_type)), [entities])
  const otherEnts = useMemo(() => entities.filter((e) => !isKeyEntity(e.entity_type)), [entities])
  const timelineEvents = timelineQ.data ?? []

  // Mutations
  const reprocess = useMutation({
    mutationFn: () => api.reprocess(documentId),
    onSuccess: () => invalidateAll(),
  })
  const saveRevision = useMutation({
    mutationFn: () =>
      api.createOcrRevision(selectedPage!.id, {
        corrected_text: editedText,
        reason: revisionReason.trim() || null,
      }),
    onSuccess: () => {
      setRevisionReason("")
      invalidateAll()
    },
  })

  // Keep the editor textarea in sync with the currently selected
  // page so switching pages reloads the draft.
  useEffect(() => {
    setEditedText(selectedPage?.text ?? "")
  }, [selectedPage?.id, selectedPage?.text])

  function invalidateAll() {
    ["document", "document-pages", "document-blocks", "document-entities", "document-timeline"].forEach(
      (key) => queryClient.invalidateQueries({ queryKey: [key, documentId] }),
    )
  }

  return {
    // queries
    document: doc,
    pages,
    blocksQ,
    entities,
    keyEnts,
    otherEnts,
    timelineEvents,
    graphQ,
    revisionsQ,
    // derived
    selectedPage,
    visiblePages,
    hashShort: shortHash(doc?.file_hash),
    hasThumbnailExt: hasThumbnailExt(doc?.extension),
    // state
    selectedPageNumber, setSelectedPageNumber,
    textQuery, setTextQuery,
    editedText, setEditedText,
    revisionReason, setRevisionReason,
    showGraph, setShowGraph,
    showBlocks, setShowBlocks,
    // mutations
    reprocess,
    saveRevision,
    // actions
    invalidateAll,
  }
}

export type DocumentDetail = ReturnType<typeof useDocumentDetail>
export type { DocumentEntity, DocumentGraph, DocumentPage, DocumentTimelineEvent }
