import { useMemo } from "react"
import { Link } from "react-router-dom"
import { ArrowRight, FileText, GitBranch, Link2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
import type { DocumentGraph } from "@/types/api"

const RELATION_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  presupuesto_pedido: { bg: "bg-[var(--info-light)]", text: "text-[var(--text-on-info)]", border: "border-[var(--info)]/30" },
  pedido_factura: { bg: "bg-[var(--success-light)]", text: "text-[var(--text-on-success)]", border: "border-[var(--success)]/30" },
  presupuesto_factura: { bg: "bg-[var(--warning-light)]", text: "text-[var(--text-on-warning)]", border: "border-[var(--warning)]/30" },
  duplicado: { bg: "bg-[var(--bg-surface-2)]", text: "text-[var(--text-muted)]", border: "border-[var(--border)]" },
  default: { bg: "bg-[var(--accent-light)]", text: "text-[var(--text-on-info)]", border: "border-[var(--accent)]/30" },
}

function getRelationStyle(relation: string) {
  return RELATION_COLORS[relation] ?? RELATION_COLORS.default
}

export function GraphView({ graph, currentDocId }: { graph: DocumentGraph; currentDocId?: number }) {
  const edgesByRelation = useMemo(() => {
    const map = new Map<string, typeof graph.edges>()
    for (const edge of graph.edges) {
      const key = edge.relation ?? "sin_relacion"
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(edge)
    }
    return map
  }, [graph.edges])

  const nodeMap = useMemo(() => {
    const map = new Map<number, (typeof graph.nodes)[0]>()
    for (const node of graph.nodes) map.set(node.document_id, node)
    return map
  }, [graph.nodes])

  return (
    <div className="space-y-4">
      {/* Summary badges */}
      <div className="flex flex-wrap gap-2">
        <Badge variant="neutral" className="gap-1"><FileText className="h-3 w-3" /> {graph.nodes.length} documentos</Badge>
        <Badge variant="info" className="gap-1"><Link2 className="h-3 w-3" /> {graph.edges.length} relaciones</Badge>
        <Badge variant="success" className="gap-1"><GitBranch className="h-3 w-3" /> {edgesByRelation.size} tipos</Badge>
      </div>

      {/* Visual node graph — center node + connected nodes */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-[13px]">Mapa de relaciones</CardTitle>
        </CardHeader>
        <CardContent className="p-4">
          <div className="flex flex-col items-center gap-4">
            {/* Center node (current document) */}
            {currentDocId && nodeMap.has(currentDocId) && (
              <div className="relative">
                <div className="flex h-16 w-16 items-center justify-center rounded-2xl border-2 border-[var(--accent)] bg-[var(--accent-light)] shadow-lg shadow-[var(--accent)]/10">
                  <FileText className="h-6 w-6 text-[var(--accent)]" />
                </div>
                <p className="mt-1.5 max-w-[120px] truncate text-center text-[10px] font-medium text-[var(--text-primary)]">
                  {nodeMap.get(currentDocId)?.filename}
                </p>
              </div>
            )}

            {/* Connection lines + connected nodes */}
            {graph.edges.length > 0 && (
              <div className="flex flex-wrap items-start justify-center gap-3">
                {graph.edges.map((edge, i) => {
                  const fromNode = nodeMap.get(edge.from_document_id)
                  const toNode = nodeMap.get(edge.to_document_id)
                  const style = getRelationStyle(edge.relation)
                  const connectedId = edge.from_document_id === currentDocId ? edge.to_document_id : edge.from_document_id
                  const connectedNode = nodeMap.get(connectedId)
                  if (!connectedNode) return null

                  return (
                    <div key={i} className="flex flex-col items-center gap-1.5">
                      {/* Arrow */}
                      <div className="flex items-center gap-1.5">
                        <span className={cn("rounded-full border px-2 py-0.5 text-[9px] font-semibold", style.bg, style.text, style.border)}>
                          {edge.relation}
                        </span>
                        <ArrowRight className="h-3 w-3 text-[var(--text-muted)]" />
                      </div>
                      {/* Connected node */}
                      <Link
                        to={`/documents/${connectedId}`}
                        className={cn(
                          "flex flex-col items-center gap-1 rounded-xl border p-3 transition-all hover:shadow-md",
                          connectedId === currentDocId ? "border-[var(--accent)] bg-[var(--accent-light)]" : "border-[var(--border)] bg-[var(--bg-surface)] hover:border-[var(--border-2)]",
                        )}
                      >
                        <div className={cn(
                          "flex h-10 w-10 items-center justify-center rounded-lg",
                          connectedId === currentDocId ? "bg-[var(--accent)] text-white" : "bg-[var(--bg-surface-2)] text-[var(--text-muted)]",
                        )}>
                          <FileText className="h-4 w-4" />
                        </div>
                        <p className="max-w-[100px] truncate text-[10px] font-medium text-[var(--text-primary)]">{connectedNode.filename}</p>
                        <p className="text-[9px] text-[var(--text-muted)]">{connectedNode.document_type}</p>
                        {edge.label && <p className="max-w-[100px] truncate text-[9px] text-[var(--text-muted)] italic">&quot;{edge.label}&quot;</p>}
                      </Link>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Edges grouped by relation type */}
      {edgesByRelation.size > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-[13px]">Relaciones por tipo</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {Array.from(edgesByRelation.entries()).map(([relation, edges]) => {
              const style = getRelationStyle(relation)
              return (
                <div key={relation}>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-semibold", style.bg, style.text, style.border)}>
                      {relation}
                    </span>
                    <span className="text-[10px] text-[var(--text-muted)]">{edges.length} relación(es)</span>
                  </div>
                  <div className="space-y-1 pl-2">
                    {edges.map((edge, i) => {
                      const from = nodeMap.get(edge.from_document_id)
                      const to = nodeMap.get(edge.to_document_id)
                      return (
                        <div key={i} className="flex items-center gap-2 text-[11px]">
                          <Link to={`/documents/${edge.from_document_id}`} className="font-medium text-[var(--accent)] hover:underline">
                            {from?.filename ?? `#${edge.from_document_id}`}
                          </Link>
                          <ArrowRight className="h-3 w-3 text-[var(--text-muted)]" />
                          <Link to={`/documents/${edge.to_document_id}`} className="font-medium text-[var(--accent)] hover:underline">
                            {to?.filename ?? `#${edge.to_document_id}`}
                          </Link>
                          {edge.label && <span className="text-[var(--text-muted)] italic">({edge.label})</span>}
                        </div>
                      )
                    })}
                  </div>
                  {relation !== Array.from(edgesByRelation.keys()).slice(-1)[0] && <Separator className="mt-3" />}
                </div>
              )
            })}
          </CardContent>
        </Card>
      )}

      {/* All nodes list */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-[13px]">Documentos relacionados ({graph.nodes.length})</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {graph.nodes.map((node) => (
              <Link
                key={node.document_id}
                to={`/documents/${node.document_id}`}
                className={cn(
                  "flex items-center gap-2 rounded-md border px-3 py-2 text-[11px] transition-colors hover:bg-[var(--bg-surface-2)]",
                  node.document_id === currentDocId ? "border-[var(--accent)] bg-[var(--accent-light)]" : "border-[var(--border)]",
                )}
              >
                <FileText className="h-3.5 w-3.5 flex-shrink-0 text-[var(--text-muted)]" />
                <span className="flex-1 truncate font-medium text-[var(--text-primary)]">{node.filename}</span>
                <span className="text-[var(--text-muted)]">{node.document_type}</span>
              </Link>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
