import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  Clock,
  Copy,
  FileWarning,
  Loader2,
  ShieldAlert,
  Upload,
  XCircle,
  type LucideIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"

type DocStatus =
  | "uploaded"
  | "queued"
  | "processing"
  | "processed"
  | "processed_ok"
  | "processed_low_quality"
  | "processed_missing_fields"
  | "needs_review"
  | "needs_human_review"
  | "failed"
  | "error"
  | "quarantined"
  | "quarantine"
  | "duplicate"
  | "archived"
  | "completed"
  | "finished"
  | "approved"
  | "rejected"
  | "pending"
  | "in_progress"
  | "running"
  | "active"
  | "warning"
  | "degraded"
  | "critical"
  | string

type StatusConfig = {
  icon: LucideIcon
  color: string
  bg: string
  textColor: string
  label: string
  action?: string
}

const statusRegistry: Record<string, StatusConfig> = {
  uploaded:         { icon: Upload,          color: "bg-[var(--sky)]",     bg: "bg-[var(--sky-light)]",      textColor: "text-[#075985]", label: "Subido",       action: "Pendiente de procesar" },
  queued:           { icon: Clock,           color: "bg-[var(--sky)]",     bg: "bg-[var(--sky-light)]",      textColor: "text-[#075985]", label: "En cola",      action: "Esperando worker" },
  processing:       { icon: Loader2,         color: "bg-[#7C3AED]",        bg: "bg-[#EDE9FE]",               textColor: "text-[#5B21B6]", label: "Procesando",   action: "En curso" },
  running:          { icon: Loader2,         color: "bg-[#7C3AED]",        bg: "bg-[#EDE9FE]",               textColor: "text-[#5B21B6]", label: "Ejecutando",   action: "En curso" },
  in_progress:      { icon: Loader2,         color: "bg-[#7C3AED]",        bg: "bg-[#EDE9FE]",               textColor: "text-[#5B21B6]", label: "En progreso",  action: "En curso" },
  active:           { icon: CheckCircle2,    color: "bg-[var(--emerald)]", bg: "bg-[var(--emerald-light)]",  textColor: "text-[#065F46]", label: "Activo",       action: "Operativo" },
  processed:        { icon: CheckCircle2,    color: "bg-[var(--emerald)]", bg: "bg-[var(--emerald-light)]",  textColor: "text-[#065F46]", label: "Procesado",    action: "Listo para usar" },
  processed_ok:     { icon: CheckCircle2,    color: "bg-[var(--emerald)]", bg: "bg-[var(--emerald-light)]",  textColor: "text-[#065F46]", label: "Calidad OK",   action: "Listo para usar" },
  completed:        { icon: CheckCircle2,    color: "bg-[var(--emerald)]", bg: "bg-[var(--emerald-light)]",  textColor: "text-[#065F46]", label: "Completado",   action: "Finalizado" },
  finished:         { icon: CheckCircle2,    color: "bg-[var(--emerald)]", bg: "bg-[var(--emerald-light)]",  textColor: "text-[#065F46]", label: "Finalizado",   action: "Finalizado" },
  approved:         { icon: CheckCircle2,    color: "bg-[var(--emerald)]", bg: "bg-[var(--emerald-light)]",  textColor: "text-[#065F46]", label: "Aprobado",     action: "Validado" },
  ready:            { icon: CheckCircle2,    color: "bg-[var(--emerald)]", bg: "bg-[var(--emerald-light)]",  textColor: "text-[#065F46]", label: "Listo",        action: "Operativo" },
  ok:               { icon: CheckCircle2,    color: "bg-[var(--emerald)]", bg: "bg-[var(--emerald-light)]",  textColor: "text-[#065F46]", label: "OK",           action: "Operativo" },
  processed_low_quality: { icon: FileWarning, color: "bg-[var(--amber)]",  bg: "bg-[var(--amber-light)]",   textColor: "text-[#92400E]", label: "Baja calidad", action: "Revisar OCR" },
  processed_missing_fields: { icon: FileWarning, color: "bg-[var(--amber)]", bg: "bg-[var(--amber-light)]", textColor: "text-[#92400E]", label: "Campos faltantes", action: "Completar datos" },
  needs_review:     { icon: FileWarning,     color: "bg-[var(--amber)]",   bg: "bg-[var(--amber-light)]",   textColor: "text-[#92400E]", label: "Revisión",    action: "Requiere revisión humana" },
  needs_human_review: { icon: FileWarning,   color: "bg-[var(--amber)]",   bg: "bg-[var(--amber-light)]",   textColor: "text-[#92400E]", label: "Revisión",    action: "Requiere revisión humana" },
  warning:          { icon: AlertTriangle,   color: "bg-[var(--amber)]",   bg: "bg-[var(--amber-light)]",   textColor: "text-[#92400E]", label: "Advertencia", action: "Requiere atención" },
  degraded:         { icon: AlertTriangle,   color: "bg-[var(--amber)]",   bg: "bg-[var(--amber-light)]",   textColor: "text-[#92400E]", label: "Degradado",   action: "Rendimiento reducido" },
  pending:          { icon: Clock,           color: "bg-[var(--amber)]",   bg: "bg-[var(--amber-light)]",   textColor: "text-[#92400E]", label: "Pendiente",   action: "Esperando" },
  failed:           { icon: XCircle,         color: "bg-[var(--rose)]",    bg: "bg-[var(--rose-light)]",    textColor: "text-[#9F1239]", label: "Fallido",     action: "Reprocesar documento" },
  error:            { icon: XCircle,         color: "bg-[var(--rose)]",    bg: "bg-[var(--rose-light)]",    textColor: "text-[#9F1239]", label: "Error",       action: "Investigar causa" },
  rejected:         { icon: XCircle,         color: "bg-[var(--rose)]",    bg: "bg-[var(--rose-light)]",    textColor: "text-[#9F1239]", label: "Rechazado",   action: "Corregir y reintentar" },
  critical:         { icon: ShieldAlert,     color: "bg-[var(--rose)]",    bg: "bg-[var(--rose-light)]",    textColor: "text-[#9F1239]", label: "Crítico",     action: "Atención inmediata" },
  blocked:          { icon: ShieldAlert,     color: "bg-[var(--rose)]",    bg: "bg-[var(--rose-light)]",    textColor: "text-[#9F1239]", label: "Bloqueado",   action: "Desbloquear" },
  quarantined:      { icon: ShieldAlert,     color: "bg-[var(--rose)]",    bg: "bg-[var(--rose-light)]",    textColor: "text-[#9F1239]", label: "Cuarentena",  action: "Revisar seguridad" },
  quarantine:       { icon: ShieldAlert,     color: "bg-[var(--rose)]",    bg: "bg-[var(--rose-light)]",    textColor: "text-[#9F1239]", label: "Cuarentena",  action: "Revisar seguridad" },
  duplicate:        { icon: Copy,            color: "bg-[var(--text-muted)]", bg: "bg-[var(--bg-surface-2)]", textColor: "text-[var(--text-secondary)]", label: "Duplicado", action: "Marcar como original" },
  archived:         { icon: Archive,         color: "bg-[var(--text-muted)]", bg: "bg-[var(--bg-surface-2)]", textColor: "text-[var(--text-secondary)]", label: "Archivado", action: "Fuera de circuito activo" },
}

function getStatusConfig(status: string | null | undefined): StatusConfig {
  const normalized = String(status ?? "").trim().toLowerCase()
  return statusRegistry[normalized] ?? {
    icon: Clock,
    color: "bg-[var(--text-muted)]",
    bg: "bg-[var(--bg-surface-2)]",
    textColor: "text-[var(--text-secondary)]",
    label: normalized || "Desconocido",
    action: undefined,
  }
}

export function StatusBadge({
  status,
  showAction = false,
  size = "sm",
  className,
}: {
  status: string
  showAction?: boolean
  size?: "sm" | "md"
  className?: string
}) {
  const cfg = getStatusConfig(status)
  const Icon = cfg.icon

  const sizeClasses = size === "sm"
    ? { icon: "h-3 w-3", text: "text-[11px]", pill: "px-2 py-0.5 gap-1" }
    : { icon: "h-3.5 w-3.5", text: "text-[12px]", pill: "px-2.5 py-1 gap-1.5" }

  return (
    <div className={cn("flex flex-col gap-0.5", className)}>
      <span className={cn("inline-flex items-center rounded-full font-medium whitespace-nowrap", sizeClasses.pill, cfg.bg, cfg.textColor)}>
        <Icon className={cn(sizeClasses.icon, "flex-shrink-0")} />
        <span className={sizeClasses.text}>{cfg.label}</span>
      </span>
      {showAction && cfg.action && (
        <span className="text-[10px] text-[var(--text-muted)] ml-5">{cfg.action}</span>
      )}
    </div>
  )
}

/**
 * Shows a visual progress bar for document pipeline stages.
 */
export function DocumentProgressBar({ status }: { status: string }) {
  const stages = [
    { key: "uploaded", label: "Subido" },
    { key: "queued", label: "En cola" },
    { key: "processing", label: "Procesando" },
    { key: "processed", label: "Procesado" },
  ]

  const currentIdx = (() => {
    const norm = String(status ?? "").trim().toLowerCase()
    if (norm === "uploaded") return 0
    if (norm === "queued") return 1
    if (norm === "processing" || norm === "running") return 2
    if (norm === "processed" || norm === "processed_ok" || norm === "completed" || norm === "finished") return 3
    if (norm === "failed" || norm === "error") return -1
    return -1
  })()

  if (currentIdx === -1) {
    const cfg = getStatusConfig(status)
    return (
      <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium", cfg.bg, cfg.textColor)}>
        <cfg.icon className="h-3 w-3" />
        {cfg.label}
      </span>
    )
  }

  return (
    <div className="flex items-center gap-1">
      {stages.map((stage, idx) => {
        const isDone = idx <= currentIdx
        const isCurrent = idx === currentIdx
        return (
          <div key={stage.key} className="flex items-center gap-1">
            <div className={cn(
              "flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors",
              isDone ? (isCurrent ? "bg-[var(--primary-light)] text-[var(--primary)]" : "bg-[var(--emerald-light)] text-[#065F46]") : "bg-[var(--bg-surface-2)] text-[var(--text-muted)]",
            )}>
              {isDone && <CheckCircle2 className="h-2.5 w-2.5" />}
              {stage.label}
            </div>
            {idx < stages.length - 1 && (
              <div className={cn("h-px w-3", isDone && idx < currentIdx ? "bg-[var(--emerald)]" : "bg-[var(--border)]")} />
            )}
          </div>
        )
      })}
    </div>
  )
}
