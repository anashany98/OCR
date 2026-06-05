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
  uploaded:         { icon: Upload,          color: "bg-[var(--info)]",     bg: "bg-[var(--info-faint)]",     textColor: "text-[var(--text-on-info)]",    label: "Subido",       action: "Pendiente de procesar" },
  queued:           { icon: Clock,           color: "bg-[var(--info)]",     bg: "bg-[var(--info-faint)]",     textColor: "text-[var(--text-on-info)]",    label: "En cola",      action: "Esperando worker" },
  processing:       { icon: Loader2,         color: "bg-[#7C5BC9]",         bg: "bg-[#F1ECFB]",               textColor: "text-[#5A3DA0]",                label: "Procesando",   action: "En curso" },
  running:          { icon: Loader2,         color: "bg-[#7C5BC9]",         bg: "bg-[#F1ECFB]",               textColor: "text-[#5A3DA0]",                label: "Ejecutando",   action: "En curso" },
  in_progress:      { icon: Loader2,         color: "bg-[#7C5BC9]",         bg: "bg-[#F1ECFB]",               textColor: "text-[#5A3DA0]",                label: "En progreso",  action: "En curso" },
  active:           { icon: CheckCircle2,    color: "bg-[var(--positive)]", bg: "bg-[var(--positive-faint)]", textColor: "text-[var(--text-on-success)]", label: "Activo",       action: "Operativo" },
  processed:        { icon: CheckCircle2,    color: "bg-[var(--positive)]", bg: "bg-[var(--positive-faint)]", textColor: "text-[var(--text-on-success)]", label: "Procesado",    action: "Listo para usar" },
  processed_ok:     { icon: CheckCircle2,    color: "bg-[var(--positive)]", bg: "bg-[var(--positive-faint)]", textColor: "text-[var(--text-on-success)]", label: "Calidad OK",   action: "Listo para usar" },
  completed:        { icon: CheckCircle2,    color: "bg-[var(--positive)]", bg: "bg-[var(--positive-faint)]", textColor: "text-[var(--text-on-success)]", label: "Completado",   action: "Finalizado" },
  finished:         { icon: CheckCircle2,    color: "bg-[var(--positive)]", bg: "bg-[var(--positive-faint)]", textColor: "text-[var(--text-on-success)]", label: "Finalizado",   action: "Finalizado" },
  approved:         { icon: CheckCircle2,    color: "bg-[var(--positive)]", bg: "bg-[var(--positive-faint)]", textColor: "text-[var(--text-on-success)]", label: "Aprobado",     action: "Validado" },
  ready:            { icon: CheckCircle2,    color: "bg-[var(--positive)]", bg: "bg-[var(--positive-faint)]", textColor: "text-[var(--text-on-success)]", label: "Listo",        action: "Operativo" },
  ok:               { icon: CheckCircle2,    color: "bg-[var(--positive)]", bg: "bg-[var(--positive-faint)]", textColor: "text-[var(--text-on-success)]", label: "OK",           action: "Operativo" },
  processed_low_quality: { icon: FileWarning, color: "bg-[var(--warning)]",  bg: "bg-[var(--warning-faint)]",  textColor: "text-[var(--text-on-warning)]", label: "Baja calidad", action: "Revisar OCR" },
  processed_missing_fields: { icon: FileWarning, color: "bg-[var(--warning)]", bg: "bg-[var(--warning-faint)]",  textColor: "text-[var(--text-on-warning)]", label: "Campos faltantes", action: "Completar datos" },
  needs_review:     { icon: FileWarning,     color: "bg-[var(--warning)]",  bg: "bg-[var(--warning-faint)]",  textColor: "text-[var(--text-on-warning)]", label: "Revisión",    action: "Requiere revisión humana" },
  needs_human_review: { icon: FileWarning,   color: "bg-[var(--warning)]",  bg: "bg-[var(--warning-faint)]",  textColor: "text-[var(--text-on-warning)]", label: "Revisión",    action: "Requiere revisión humana" },
  warning:          { icon: AlertTriangle,   color: "bg-[var(--warning)]",  bg: "bg-[var(--warning-faint)]",  textColor: "text-[var(--text-on-warning)]", label: "Advertencia", action: "Requiere atención" },
  degraded:         { icon: AlertTriangle,   color: "bg-[var(--warning)]",  bg: "bg-[var(--warning-faint)]",  textColor: "text-[var(--text-on-warning)]", label: "Degradado",   action: "Rendimiento reducido" },
  pending:          { icon: Clock,           color: "bg-[var(--warning)]",  bg: "bg-[var(--warning-faint)]",  textColor: "text-[var(--text-on-warning)]", label: "Pendiente",   action: "Esperando" },
  failed:           { icon: XCircle,         color: "bg-[var(--danger)]",   bg: "bg-[var(--danger-faint)]",   textColor: "text-[var(--text-on-danger)]",  label: "Fallido",     action: "Reprocesar documento" },
  error:            { icon: XCircle,         color: "bg-[var(--danger)]",   bg: "bg-[var(--danger-faint)]",   textColor: "text-[var(--text-on-danger)]",  label: "Error",       action: "Investigar causa" },
  rejected:         { icon: XCircle,         color: "bg-[var(--danger)]",   bg: "bg-[var(--danger-faint)]",   textColor: "text-[var(--text-on-danger)]",  label: "Rechazado",   action: "Corregir y reintentar" },
  critical:         { icon: ShieldAlert,     color: "bg-[var(--danger)]",   bg: "bg-[var(--danger-faint)]",   textColor: "text-[var(--text-on-danger)]",  label: "Crítico",     action: "Atención inmediata" },
  blocked:          { icon: ShieldAlert,     color: "bg-[var(--danger)]",   bg: "bg-[var(--danger-faint)]",   textColor: "text-[var(--text-on-danger)]",  label: "Bloqueado",   action: "Desbloquear" },
  quarantined:      { icon: ShieldAlert,     color: "bg-[var(--danger)]",   bg: "bg-[var(--danger-faint)]",   textColor: "text-[var(--text-on-danger)]",  label: "Cuarentena",  action: "Revisar seguridad" },
  quarantine:       { icon: ShieldAlert,     color: "bg-[var(--danger)]",   bg: "bg-[var(--danger-faint)]",   textColor: "text-[var(--text-on-danger)]",  label: "Cuarentena",  action: "Revisar seguridad" },
  duplicate:        { icon: Copy,            color: "bg-[var(--text-muted)]", bg: "bg-[var(--bg-surface-2)]", textColor: "text-[var(--text-secondary)]", label: "Duplicado", action: "Marcar como original" },
  archived:         { icon: Archive,         color: "bg-[var(--text-muted)]", bg: "bg-[var(--bg-surface-2)]", textColor: "text-[var(--text-secondary)]", label: "Archivado", action: "Fuera de circuito activo" },
}

function getStatusConfig(status: string | null | undefined): StatusConfig {
  const normalized = String(status ?? "").trim().toLowerCase()
  return (
    statusRegistry[normalized] ?? {
      icon: Clock,
      color: "bg-[var(--text-muted)]",
      bg: "bg-[var(--bg-surface-2)]",
      textColor: "text-[var(--text-secondary)]",
      label: normalized || "Desconocido",
      action: undefined,
    }
  )
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

  const sizeClasses =
    size === "sm"
      ? { icon: "h-3 w-3", text: "text-[11px]", pill: "px-2.5 py-0.5 gap-1" }
      : { icon: "h-3.5 w-3.5", text: "text-[12px]", pill: "px-3 py-1 gap-1.5" }

  return (
    <div className={cn("flex flex-col gap-0.5", className)}>
      <span
        className={cn(
          "inline-flex w-fit items-center rounded-full font-medium whitespace-nowrap",
          sizeClasses.pill,
          cfg.bg,
          cfg.textColor,
        )}
      >
        <Icon className={cn(sizeClasses.icon, "flex-shrink-0")} aria-hidden="true" />
        <span className={sizeClasses.text}>{cfg.label}</span>
      </span>
      {showAction && cfg.action && (
        <span className="ml-1 text-[10px] text-[var(--text-muted)]">{cfg.action}</span>
      )}
    </div>
  )
}

/**
 * Shows a visual progress bar for document pipeline stages. Editorial style:
 * rounded pills connected by hairline dividers.
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
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-medium",
          cfg.bg,
          cfg.textColor,
        )}
      >
        <cfg.icon className="h-3 w-3" aria-hidden="true" />
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
            <div
              className={cn(
                "flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[10px] font-medium transition-colors duration-base ease-out",
                isCurrent
                  ? "bg-[var(--accent-faint)] text-[var(--text-on-warning)]"
                  : isDone
                    ? "bg-[var(--positive-faint)] text-[var(--text-on-success)]"
                    : "bg-[var(--bg-surface-2)] text-[var(--text-muted)]",
              )}
            >
              {isDone && <CheckCircle2 className="h-2.5 w-2.5" aria-hidden="true" />}
              {stage.label}
            </div>
            {idx < stages.length - 1 && (
              <div className={cn("h-px w-3", isDone && idx < currentIdx ? "bg-[var(--positive)]" : "bg-[var(--border)]")} />
            )}
          </div>
        )
      })}
    </div>
  )
}
