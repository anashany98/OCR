import { useState } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import {
  AlertTriangle,
  ArrowRight,
  Brain,
  CheckCircle2,
  Clock,
  Edit3,
  ExternalLink,
  Eye,
  FlaskConical,
  History,
  Power,
  PowerOff,
  RotateCcw,
  TrendingUp,
  XCircle,
} from "lucide-react"

import type { ClassificationSuggestion, LearnedPattern } from "@/types/api"
import { ConfidenceBadge } from "@/components/layout/ConfidenceBadge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { cn, formatDate } from "@/lib/utils"
import { useAdminLearningData } from "./useAdminLearningData"

interface MutationLike<TData = unknown> {
  mutate: (vars: number) => void
  isPending: boolean
  data?: TData
  isError: boolean
  error: Error | null
}

interface LearningViewProps {
  suggestions: ClassificationSuggestion[]
  patterns: LearnedPattern[]
  counts?: Record<string, number>
  approveSuggestion: MutationLike
  rejectSuggestion: MutationLike
  enablePattern: MutationLike
  disablePattern: MutationLike
}

const suggestionLabels: Record<string, string> = {
  classification_correction: "Corrección de tipo",
  entity_link: "Vinculación de documentos",
  classification_rule: "Regla de clasificación",
  quality_feedback: "Feedback de calidad",
}

const statusLabels: Record<string, string> = {
  pending: "Pendiente",
  approved: "Aprobada",
  rejected: "Rechazada",
  applied: "Aplicada",
  active: "Activo",
  disabled: "Desactivado",
}

function riskLevel(confidence: number): { level: string; color: string; bg: string } {
  if (confidence >= 0.85)
    return { level: "Bajo", color: "text-[#065F46]", bg: "bg-[var(--emerald-light)]" }
  if (confidence >= 0.7)
    return { level: "Medio", color: "text-[#92400E]", bg: "bg-[var(--amber-light)]" }
  return { level: "Alto", color: "text-[#9F1239]", bg: "bg-[var(--rose-light)]" }
}

function estimatedImpact(suggestion: ClassificationSuggestion): { docs: number; label: string } {
  if (suggestion.suggestion_type === "classification_rule") {
    return { docs: 5, label: "~5 docs similares" }
  }
  if (suggestion.suggestion_type === "classification_correction") {
    return { docs: 1, label: "Solo este documento" }
  }
  return { docs: 1, label: "Impacto directo" }
}

function LearningView({
  suggestions,
  patterns,
  counts,
  approveSuggestion,
  rejectSuggestion,
  enablePattern,
  disablePattern,
}: LearningViewProps) {
  const [filter, setFilter] = useState<"pending" | "approved" | "all">("pending")
  const [selectedSuggestion, setSelectedSuggestion] = useState<ClassificationSuggestion | null>(
    null,
  )
  const [showHistory, setShowHistory] = useState(false)

  const filtered = (() => {
    if (filter === "pending") return suggestions.filter((s) => s.status === "pending")
    if (filter === "approved")
      return suggestions.filter((s) => s.status === "approved" || s.status === "applied")
    return suggestions
  })()

  const historyItems = suggestions.filter((s) => s.status !== "pending")
  const activePatterns = patterns.filter((p) => p.status === "active")
  const disabledPatterns = patterns.filter((p) => p.status === "disabled")
  const pendingCount = counts?.pending ?? suggestions.filter((s) => s.status === "pending").length

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-[16px]">
            <Brain className="h-5 w-5 text-[var(--primary)]" />
            Bucle de Mejora
          </CardTitle>
          <CardDescription>
            Sugerencias del agente externo y patrones aprendidos. El sistema Celery aplica las
            aprobadas automáticamente cada 5 minutos.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-3">
            <CountBadge label="Pendientes" value={pendingCount} variant="warning" />
            <CountBadge label="Aprobadas" value={counts?.approved ?? 0} variant="success" />
            <CountBadge label="Rechazadas" value={counts?.rejected ?? 0} variant="danger" />
            <CountBadge label="Aplicadas" value={counts?.applied ?? 0} variant="info" />
            <CountBadge label="Patrones activos" value={activePatterns.length} variant="neutral" />
          </div>
        </CardContent>
      </Card>

      {selectedSuggestion && (
        <SuggestionDetailCard
          suggestion={selectedSuggestion}
          onClose={() => setSelectedSuggestion(null)}
          onApprove={() => {
            approveSuggestion.mutate(selectedSuggestion.id)
            setSelectedSuggestion(null)
          }}
          onReject={() => {
            rejectSuggestion.mutate(selectedSuggestion.id)
            setSelectedSuggestion(null)
          }}
          isApproving={approveSuggestion.isPending}
          isRejecting={rejectSuggestion.isPending}
        />
      )}

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3">
          <div>
            <CardTitle className="text-[14px]">Sugerencias de clasificación</CardTitle>
            <CardDescription>
              Propuestas por el agente externo para revisar y aprobar.
            </CardDescription>
          </div>
          <div className="flex gap-1">
            {(["pending", "approved", "all"] as const).map((f) => (
              <Button
                key={f}
                size="sm"
                variant={filter === f ? "default" : "outline"}
                className="h-7 text-xs"
                onClick={() => setFilter(f)}
              >
                {f === "pending" ? "Pendientes" : f === "approved" ? "Aprobadas" : "Todas"}
              </Button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {filtered.length === 0 ? (
            <p className="py-4 text-center text-sm text-[var(--text-muted)]">
              {filter === "pending"
                ? "Sin sugerencias pendientes de revisión."
                : "Sin sugerencias registradas."}
            </p>
          ) : (
            filtered.map((s) => {
              const risk = riskLevel(s.confidence)
              const impact = estimatedImpact(s)
              return (
                <div
                  key={s.id}
                  className="rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-4 transition-all hover:border-[var(--border-2)] hover:shadow-sm"
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="neutral" className="text-[10px]">
                          #{s.id} · {suggestionLabels[s.suggestion_type] ?? s.suggestion_type}
                        </Badge>
                        <StatusBadge status={s.status} />
                        <ConfidenceBadge value={s.confidence} />
                        <span
                          className={cn(
                            "rounded px-1.5 py-0.5 text-[10px] font-semibold",
                            risk.bg,
                            risk.color,
                          )}
                        >
                          Riesgo {risk.level}
                        </span>
                      </div>
                      <p className="text-[13px] text-[var(--text-primary)] leading-relaxed">
                        {s.reason}
                      </p>
                      {s.suggested_document_type && (
                        <div className="flex items-center gap-2 rounded-md bg-[var(--bg-surface-2)] px-3 py-1.5">
                          <span className="text-xs text-[var(--text-muted)]">Tipo actual:</span>
                          <Badge variant="outline" className="text-[10px]">
                            {s.current_document_type ?? "desconocido"}
                          </Badge>
                          <ArrowRight className="h-3 w-3 text-[var(--text-muted)]" />
                          <Badge variant="default" className="text-[10px]">
                            {s.suggested_document_type}
                          </Badge>
                        </div>
                      )}
                      {s.pattern_value && (
                        <div className="rounded-md bg-[var(--bg-surface-2)] px-3 py-1.5">
                          <code className="text-xs text-[var(--text-secondary)]">
                            Patrón: {s.pattern_value}
                          </code>
                          <span className="mx-2 text-[var(--text-muted)]">→</span>
                          <span className="text-xs font-medium">{s.target_action ?? "?"}</span>
                        </div>
                      )}
                      {s.evidence && Object.keys(s.evidence).length > 0 && (
                        <details className="text-xs">
                          <summary className="cursor-pointer text-[var(--sky)] hover:underline">
                            Ver evidencia
                          </summary>
                          <pre className="mt-1 max-h-[120px] overflow-auto rounded-md bg-[var(--bg-surface-2)] p-2 text-[11px]">
                            {JSON.stringify(s.evidence, null, 2)}
                          </pre>
                        </details>
                      )}
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)]">
                        <span className="inline-flex items-center gap-1">
                          <Link
                            to={`/documents/${s.document_id}`}
                            className="text-[var(--sky)] hover:underline inline-flex items-center gap-0.5"
                          >
                            <ExternalLink className="h-3 w-3" />
                            Doc #{s.document_id}
                          </Link>
                        </span>
                        {s.integration_client_id && (
                          <span>Propuesto por cliente #{s.integration_client_id}</span>
                        )}
                        <span className="inline-flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {formatDate(s.created_at)}
                        </span>
                        <span title="Impacto estimado" className="inline-flex items-center gap-1">
                          <TrendingUp className="h-3 w-3" />
                          {impact.label}
                        </span>
                        <span>
                          ·{" "}
                          {s.suggestion_type === "classification_rule"
                            ? "Regla futura"
                            : "Corrección puntual"}
                        </span>
                      </div>
                    </div>
                    <div className="flex flex-col gap-1.5 sm:min-w-[180px] sm:items-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-full justify-start text-xs"
                        onClick={() => setSelectedSuggestion(s)}
                      >
                        <Eye className="mr-1 h-3 w-3" /> Ver detalle
                      </Button>
                      {s.status === "pending" && (
                        <>
                          <Button
                            size="sm"
                            className="h-7 w-full justify-start text-xs"
                            disabled={approveSuggestion.isPending}
                            onClick={() => approveSuggestion.mutate(s.id)}
                          >
                            <CheckCircle2 className="mr-1 h-3 w-3" />
                            Aprobar solo este
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 w-full justify-start text-xs"
                            disabled={approveSuggestion.isPending}
                            onClick={() => approveSuggestion.mutate(s.id)}
                          >
                            <Brain className="mr-1 h-3 w-3" />
                            {s.suggestion_type === "classification_rule"
                              ? "Aprobar regla"
                              : "Aprobar como regla"}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-7 w-full justify-start text-xs"
                            disabled={rejectSuggestion.isPending}
                            onClick={() => rejectSuggestion.mutate(s.id)}
                          >
                            <XCircle className="mr-1 h-3 w-3" /> Rechazar
                          </Button>
                        </>
                      )}
                      {s.status !== "pending" && (
                        <div className="text-xs text-[var(--text-muted)] text-right">
                          {s.reviewed_at && <p>Revisada: {formatDate(s.reviewed_at)}</p>}
                          {s.reviewed_by_user_id && <p>Por usuario #{s.reviewed_by_user_id}</p>}
                          {s.applied_at && <p>Aplicada: {formatDate(s.applied_at)}</p>}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })
          )}
          {(approveSuggestion.isError || rejectSuggestion.isError) && (
            <p className="mt-2 text-sm text-destructive">
              {(approveSuggestion.error ?? rejectSuggestion.error)?.message}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <button
          type="button"
          onClick={() => setShowHistory(!showHistory)}
          className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-[var(--bg-surface-2)]/80"
        >
          <CardTitle className="text-[14px] flex items-center gap-2">
            <History className="h-4 w-4 text-[var(--text-muted)]" />
            Historial de cambios ({historyItems.length})
          </CardTitle>
          {showHistory ? (
            <ArrowRight className="h-4 w-4 rotate-90 text-[var(--text-muted)]" />
          ) : (
            <ArrowRight className="h-4 w-4 text-[var(--text-muted)]" />
          )}
        </button>
        {showHistory && (
          <CardContent className="border-t p-3">
            {historyItems.length === 0 ? (
              <p className="text-sm text-[var(--text-muted)]">Sin cambios registrados todavía.</p>
            ) : (
              <div className="space-y-2">
                {historyItems.slice(0, 20).map((s) => {
                  const impact = estimatedImpact(s)
                  return (
                    <div
                      key={s.id}
                      className="flex items-start gap-3 rounded-md border p-3 text-sm"
                    >
                      <div
                        className={cn(
                          "mt-1 h-2.5 w-2.5 rounded-full flex-shrink-0",
                          s.status === "applied"
                            ? "bg-[var(--emerald)]"
                            : s.status === "approved"
                              ? "bg-[var(--sky)]"
                              : "bg-[var(--rose)]",
                        )}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="outline" className="text-[10px]">
                            {suggestionLabels[s.suggestion_type] ?? s.suggestion_type}
                          </Badge>
                          <Badge
                            variant={
                              s.status === "applied"
                                ? "success"
                                : s.status === "approved"
                                  ? "info"
                                  : "danger"
                            }
                            className="text-[10px]"
                          >
                            {statusLabels[s.status] ?? s.status}
                          </Badge>
                        </div>
                        <p className="mt-1 text-xs text-[var(--text-secondary)] line-clamp-2">
                          {s.reason}
                        </p>
                        <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-[var(--text-muted)]">
                          <span>Doc #{s.document_id}</span>
                          <span>{impact.label}</span>
                          {s.reviewed_at && <span>Revisado: {formatDate(s.reviewed_at)}</span>}
                          {s.reviewed_by_user_id && <span>Por: #{s.reviewed_by_user_id}</span>}
                          {s.applied_at && <span>Aplicado: {formatDate(s.applied_at)}</span>}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        )}
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-[14px] flex items-center gap-2">
            <Brain className="h-4 w-4 text-[var(--primary)]" />
            Patrones aprendidos
          </CardTitle>
          <CardDescription>
            {activePatterns.length} activos · {disabledPatterns.length} desactivados ·{" "}
            {patterns.reduce((sum, p) => sum + p.applied_count, 0)} aplicaciones totales
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {patterns.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">
              Sin patrones aprendidos todavía. Aprueba sugerencias como regla para que aparezcan
              aquí.
            </p>
          ) : (
            patterns.map((p) => (
              <div
                key={p.id}
                className={cn(
                  "rounded-lg border p-4 transition-all",
                  p.status === "active"
                    ? "border-[var(--emerald-light)] bg-[var(--emerald-light)]/10"
                    : "border-[var(--border)] bg-[var(--bg-surface-2)]/50",
                )}
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="text-[10px] font-mono">
                        #{p.id}
                      </Badge>
                      <Badge variant="neutral" className="text-[10px]">
                        {p.pattern_type}
                      </Badge>
                      <Badge
                        variant={p.status === "active" ? "success" : "neutral"}
                        className="text-[10px]"
                      >
                        {statusLabels[p.status] ?? p.status}
                      </Badge>
                      <ConfidenceBadge value={p.confidence} />
                    </div>
                    <code className="text-xs bg-[var(--bg-surface-2)] rounded px-2 py-0.5 block">
                      {p.pattern_value}
                    </code>
                    <p className="text-xs text-[var(--text-secondary)]">
                      Acción: <strong>{p.target_action}</strong>
                      {p.target_class && (
                        <>
                          {" "}
                          → <strong>{p.target_class}</strong>
                        </>
                      )}
                    </p>
                    <div className="flex flex-wrap gap-x-4 text-[11px] text-[var(--text-muted)]">
                      <span className="inline-flex items-center gap-1">
                        <TrendingUp className="h-3 w-3" />
                        {p.applied_count} aplicaciones
                      </span>
                      {p.last_applied_at && <span>Última: {formatDate(p.last_applied_at)}</span>}
                      <span>Creado: {formatDate(p.created_at)}</span>
                    </div>
                  </div>
                  <div className="flex gap-1.5 sm:min-w-[130px] sm:justify-end">
                    {p.status === "active" ? (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs"
                          disabled={disablePattern.isPending}
                          onClick={() => disablePattern.mutate(p.id)}
                        >
                          <PowerOff className="mr-1 h-3 w-3" /> Desactivar
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs text-[var(--text-muted)]"
                          onClick={() =>
                            toast.info("Funcionalidad próximamente")
                          }
                        >
                          <RotateCcw className="mr-1 h-3 w-3" /> Rollback
                        </Button>
                      </>
                    ) : p.status === "disabled" ? (
                      <Button
                        size="sm"
                        className="h-7 text-xs"
                        disabled={enablePattern.isPending}
                        onClick={() => enablePattern.mutate(p.id)}
                      >
                        <Power className="mr-1 h-3 w-3" /> Activar
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card className="border-dashed">
        <CardContent className="flex items-start gap-3 py-4">
          <FlaskConical className="mt-0.5 h-4 w-4 text-[var(--amber)]" />
          <div>
            <p className="text-[13px] font-semibold text-[#92400E]">Simulador de impacto</p>
            <p className="text-xs text-[var(--text-muted)] mt-1">
              Esta funcionalidad permitirá simular el impacto de aprobar una regla antes de
              aplicarla, mostrando cuántos documentos se verían afectados. Pendiente de implementar
              en backend.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function SuggestionDetailCard({
  suggestion,
  onClose,
  onApprove,
  onReject,
  isApproving,
  isRejecting,
}: {
  suggestion: ClassificationSuggestion
  onClose: () => void
  onApprove: () => void
  onReject: () => void
  isApproving: boolean
  isRejecting: boolean
}) {
  const risk = riskLevel(suggestion.confidence)
  const impact = estimatedImpact(suggestion)

  return (
    <Card className="border-[var(--primary-light)] ring-1 ring-[var(--primary-light)]">
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="text-[14px]">Detalle de sugerencia #{suggestion.id}</CardTitle>
          <CardDescription>
            {suggestionLabels[suggestion.suggestion_type] ?? suggestion.suggestion_type}
          </CardDescription>
        </div>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
          <XCircle className="h-4 w-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <InfoItem
            label="Documento afectado"
            value={
              <Link
                to={`/documents/${suggestion.document_id}`}
                className="text-[var(--sky)] hover:underline"
              >
                #{suggestion.document_id}
              </Link>
            }
          />
          <InfoItem label="Tipo actual" value={suggestion.current_document_type ?? "—"} />
          <InfoItem label="Tipo sugerido" value={suggestion.suggested_document_type ?? "—"} />
          <InfoItem label="Confianza" value={<ConfidenceBadge value={suggestion.confidence} />} />
          <InfoItem
            label="Riesgo"
            value={
              <span
                className={cn("rounded px-1.5 py-0.5 text-xs font-semibold", risk.bg, risk.color)}
              >
                {risk.level}
              </span>
            }
          />
          <InfoItem label="Impacto estimado" value={impact.label} />
          <InfoItem
            label="Propuesto por"
            value={
              suggestion.integration_client_id
                ? `Cliente #${suggestion.integration_client_id}`
                : "Sistema"
            }
          />
          <InfoItem label="Fecha" value={formatDate(suggestion.created_at)} />
        </div>

        <div>
          <h4 className="text-xs font-semibold uppercase text-[var(--text-muted)] mb-1">Motivo</h4>
          <p className="text-sm text-[var(--text-primary)]">{suggestion.reason}</p>
        </div>

        {suggestion.evidence && Object.keys(suggestion.evidence).length > 0 && (
          <div>
            <h4 className="text-xs font-semibold uppercase text-[var(--text-muted)] mb-1">
              Evidencia
            </h4>
            <pre className="rounded-md bg-[var(--bg-surface-2)] p-3 text-xs overflow-auto max-h-[200px]">
              {JSON.stringify(suggestion.evidence, null, 2)}
            </pre>
          </div>
        )}

        {suggestion.pattern_value && (
          <div>
            <h4 className="text-xs font-semibold uppercase text-[var(--text-muted)] mb-1">
              Patrón detectado
            </h4>
            <code className="rounded bg-[var(--bg-surface-2)] px-2 py-1 text-xs">
              {suggestion.pattern_value}
            </code>
            <p className="mt-1 text-xs text-[var(--text-muted)]">
              Acción propuesta: {suggestion.target_action ?? "—"}
            </p>
          </div>
        )}

        {suggestion.suggestion_type === "classification_rule" && (
          <div className="flex items-start gap-2 rounded-md border border-[var(--sky-light)] bg-[var(--sky-light)]/10 p-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-[var(--sky)]" />
            <div>
              <p className="text-xs font-medium text-[#075985]">
                Documentos potencialmente afectados
              </p>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                El sistema buscará documentos con patrones similares al aplicar esta regla.
                Funcionalidad de simulación pendiente.
              </p>
            </div>
          </div>
        )}

        <div className="flex flex-wrap gap-2 border-t pt-3">
          <Button
            size="sm"
            className="h-8 text-xs gap-1"
            disabled={isApproving}
            onClick={onApprove}
          >
            <CheckCircle2 className="h-3.5 w-3.5" /> Aprobar solo este documento
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs gap-1"
            disabled={isApproving}
            onClick={onApprove}
          >
            <Brain className="h-3.5 w-3.5" /> Aprobar como regla futura
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs gap-1"
            disabled={isRejecting}
            onClick={onReject}
          >
            <XCircle className="h-3.5 w-3.5" /> Rechazar
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-8 text-xs gap-1 text-[var(--amber)]"
            onClick={() => toast.info("Funcionalidad próximamente")}
          >
            <Edit3 className="h-3.5 w-3.5" /> Editar regla
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="h-8 text-xs gap-1 text-[var(--sky)]"
            onClick={() =>
              toast.info("Funcionalidad próximamente")
            }
          >
            <FlaskConical className="h-3.5 w-3.5" /> Simular impacto
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function InfoItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-md border bg-[var(--bg-surface)] px-3 py-2">
      <p className="text-[10px] font-semibold uppercase text-[var(--text-muted)]">{label}</p>
      <div className="mt-0.5 text-sm">{value}</div>
    </div>
  )
}

function CountBadge({
  label,
  value,
  variant,
}: {
  label: string
  value: number
  variant: "warning" | "success" | "danger" | "info" | "neutral"
}) {
  const colors = {
    warning: "border-[var(--amber-light)] bg-[var(--amber-light)]/30 text-[#92400E]",
    success: "border-[var(--emerald-light)] bg-[var(--emerald-light)]/30 text-[#065F46]",
    danger: "border-[var(--rose-light)] bg-[var(--rose-light)]/30 text-[#9F1239]",
    info: "border-[var(--sky-light)] bg-[var(--sky-light)]/30 text-[#075985]",
    neutral: "border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-primary)]",
  }
  return (
    <div className={cn("flex items-center gap-2 rounded-lg border px-4 py-2.5", colors[variant])}>
      <span className="text-2xl font-bold">{value}</span>
      <span className="text-xs font-medium">{label}</span>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const variants: Record<string, "success" | "warning" | "danger" | "info" | "neutral"> = {
    pending: "warning",
    approved: "info",
    rejected: "danger",
    applied: "success",
    active: "success",
    disabled: "neutral",
  }
  return (
    <Badge variant={variants[status] ?? "neutral"} className="text-[10px]">
      {statusLabels[status] ?? status}
    </Badge>
  )
}

/** F4b - Learning admin sub-page. Lazy-loaded via the router. */
export function AdminLearningPage() {
  const { queries, mutations } = useAdminLearningData()

  return (
    <LearningView
      suggestions={queries.learningSuggestions.data ?? []}
      patterns={queries.learnedPatterns.data ?? []}
      counts={queries.learningCounts.data}
      approveSuggestion={{
        mutate: (id: number) => mutations.approveSuggestion.mutate(id),
        isPending: mutations.approveSuggestion.isPending,
        data: mutations.approveSuggestion.data,
        isError: mutations.approveSuggestion.isError,
        error: mutations.approveSuggestion.error,
      }}
      rejectSuggestion={{
        mutate: (id: number) => mutations.rejectSuggestion.mutate(id),
        isPending: mutations.rejectSuggestion.isPending,
        data: mutations.rejectSuggestion.data,
        isError: mutations.rejectSuggestion.isError,
        error: mutations.rejectSuggestion.error,
      }}
      enablePattern={{
        mutate: (id: number) => mutations.enablePattern.mutate(id),
        isPending: mutations.enablePattern.isPending,
        data: mutations.enablePattern.data,
        isError: mutations.enablePattern.isError,
        error: mutations.enablePattern.error,
      }}
      disablePattern={{
        mutate: (id: number) => mutations.disablePattern.mutate(id),
        isPending: mutations.disablePattern.isPending,
        data: mutations.disablePattern.data,
        isError: mutations.disablePattern.isError,
        error: mutations.disablePattern.error,
      }}
    />
  )
}
