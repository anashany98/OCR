import type { BadgeProps } from "@/components/ui/badge"
import { Badge } from "@/components/ui/badge"
import { HardDrive } from "lucide-react"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

export const inputFolders = [
  "/data/input/presupuestos",
  "/data/input/pedidos",
  "/data/input/facturas",
  "/data/input/planos",
  "/data/input/imagenes",
  "/data/input/otros",
]

export function SimpleTable({ headings, rows }: { headings: string[]; rows: string[][] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {headings.map((heading) => (
            <TableHead key={heading}>{heading}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow key={index}>
            {row.map((cell, cellIndex) => (
              <TableCell key={cellIndex}>{cell}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export function MetricBlock({ title, values }: { title: string; values?: Record<string, number> }) {
  return (
    <div>
      <p className="mb-1 font-medium">{title}</p>
      <div className="flex flex-wrap gap-2">
        {Object.entries(values ?? {}).map(([key, value]) => (
          <Badge key={key} variant="outline">
            {key}: {value}
          </Badge>
        ))}
        {!Object.keys(values ?? {}).length ? (
          <span className="text-muted-foreground">Sin datos</span>
        ) : null}
      </div>
    </div>
  )
}

export function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
    </div>
  )
}

export function ConfigStatus({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone: BadgeProps["variant"]
}) {
  return (
    <div className="rounded-md border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-2">
        <Badge variant={tone}>{value}</Badge>
      </div>
    </div>
  )
}

export function DiskLine({
  label,
  usage,
}: {
  label: string
  usage?: { path: string; total: number; used: number; free: number }
}) {
  const usedPercent = usage?.total ? Math.round((usage.used / usage.total) * 100) : 0
  return (
    <div className="rounded-md border p-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 font-medium">
          <HardDrive className="size-4 text-muted-foreground" />
          {label}
        </span>
        <span className="text-muted-foreground">{usedPercent}% usado</span>
      </div>
      <div className="h-2 overflow-hidden rounded bg-muted">
        <div className="h-full bg-primary" style={{ width: `${Math.min(usedPercent, 100)}%` }} />
      </div>
      <p className="mt-1 truncate text-xs text-muted-foreground">{usage?.path ?? "-"}</p>
    </div>
  )
}

export function formatGigabytes(bytes: number) {
  return (bytes / 1024 / 1024 / 1024).toFixed(2)
}

export function formatDuration(seconds?: number | null) {
  if (seconds == null) return "-"
  if (seconds < 60) return Math.round(seconds) + "s"
  if (seconds < 3600) return Math.round(seconds / 60) + "min"
  return (seconds / 3600).toFixed(1) + "h"
}

export function optionalId(value: string) {
  const numeric = Number(value)
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null
}

export function ids(value: string) {
  return value
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item) && item > 0)
}

export function csv(value: string) {
  return value
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
}

export function parseJsonObject(value: string) {
  const parsed = JSON.parse(value || "{}")
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Los argumentos deben ser un objeto JSON")
  }
  return parsed as Record<string, unknown>
}
