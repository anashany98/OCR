import { useQuery } from "@tanstack/react-query"
import {
  BarChart3,
  Brain,
  FileText,
  HardDrive,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react"
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { MetricTile } from "@/components/layout/MetricTile"
import { LoadingState } from "@/components/layout/LoadingState"
import { formatBytes } from "@/lib/utils"

const CHART_COLORS = [
  "#10b981", // emerald
  "#3b82f6", // blue
  "#f59e0b", // amber
  "#ef4444", // red
  "#8b5cf6", // violet
  "#06b6d4", // cyan
]

const STATUS_COLORS: Record<string, string> = {
  processed: "#10b981",
  pending: "#f59e0b",
  processing: "#3b82f6",
  failed: "#ef4444",
  needs_review: "#f97316",
  duplicate: "#8b5cf6",
}

export function AdminDashboardPage() {
  const dashboard = useQuery({
    queryKey: ["admin-dashboard"],
    queryFn: () => request("/admin/dashboard"),
    refetchInterval: 30000,
  })

  const activity = useQuery({
    queryKey: ["admin-dashboard-activity"],
    queryFn: () => request("/admin/dashboard/activity?days=14"),
  })

  const workers = useQuery({
    queryKey: ["admin-dashboard-workers"],
    queryFn: () => request("/admin-dashboard/workers"),
    refetchInterval: 10000,
  })

  if (dashboard.isLoading) {
    return <LoadingState label="Cargando dashboard..." />
  }

  const data = dashboard.data
  if (!data) return null

  const activityData = activity.data
  const workersData = workers.data

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">Dashboard</h2>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricTile
          icon={<FileText className="h-4 w-4" />}
          title="Documentos"
          value={data.documents.total}
          meta={`${data.documents.today} hoy`}
        />
        <MetricTile
          icon={<Zap className="h-4 w-4" />}
          title="Procesando"
          value={data.processing.currently_processing}
          meta={`${data.processing.failed_today} fallos hoy`}
        />
        <MetricTile
          icon={<Brain className="h-4 w-4" />}
          title="Consultas IA"
          value={data.ai.total_questions}
          meta={`${data.ai.questions_today} hoy`}
        />
        <MetricTile
          icon={<Users className="h-4 w-4" />}
          title="Usuarios activos"
          value={data.users.active_today}
          meta={`${data.users.total} total`}
        />
      </div>

      {/* Charts Row 1: Documents + Confidence Trend */}
      {activityData && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <BarChart3 className="h-4 w-4" />
                Documentos por día
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={activityData.documents_per_day}>
                  <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v) => v.slice(5)}
                  />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    labelFormatter={(v) => new Date(v).toLocaleDateString("es-ES")}
                  />
                  <Bar
                    dataKey="count"
                    fill="#3b82f6"
                    radius={[4, 4, 0, 0]}
                    name="Documentos"
                  />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <TrendingUp className="h-4 w-4" />
                Confianza OCR (tendencia)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={activityData.confidence_trend}>
                  <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v) => v.slice(5)}
                  />
                  <YAxis
                    tick={{ fontSize: 11 }}
                    domain={[0, 1]}
                    tickFormatter={(v) => `${Math.round(v * 100)}%`}
                  />
                  <Tooltip
                    formatter={(v) => [`${Math.round(Number(v) * 100)}%`, "Confianza"]}
                    labelFormatter={(v) => new Date(v).toLocaleDateString("es-ES")}
                  />
                  <Line
                    type="monotone"
                    dataKey="confidence"
                    stroke="#10b981"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    name="Confianza"
                  />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Charts Row 2: AI Questions + Failed Jobs */}
      {activityData && (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Brain className="h-4 w-4" />
                Consultas IA por día
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={activityData.questions_per_day}>
                  <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v) => v.slice(5)}
                  />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    labelFormatter={(v) => new Date(v).toLocaleDateString("es-ES")}
                  />
                  <Line
                    type="monotone"
                    dataKey="count"
                    stroke="#8b5cf6"
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    name="Consultas"
                  />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Zap className="h-4 w-4" />
                Trabajos procesados vs fallidos
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={activityData.jobs_per_day}>
                  <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11 }}
                    tickFormatter={(v) => v.slice(5)}
                  />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    labelFormatter={(v) => new Date(v).toLocaleDateString("es-ES")}
                  />
                  <Bar
                    dataKey="count"
                    fill="#10b981"
                    radius={[4, 4, 0, 0]}
                    name="Procesados"
                  />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Document Status + Type Distribution */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Documentos por estado</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-6">
              <ResponsiveContainer width={120} height={120}>
                <PieChart>
                  <Pie
                    data={Object.entries(data.documents.by_status).map(([name, value]) => ({
                      name,
                      value,
                    }))}
                    cx="50%"
                    cy="50%"
                    innerRadius={30}
                    outerRadius={50}
                    paddingAngle={2}
                    dataKey="value"
                  >
                    {Object.entries(data.documents.by_status).map(([status], index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={STATUS_COLORS[status] || CHART_COLORS[index % CHART_COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-2">
                {Object.entries(data.documents.by_status).map(([status, count]) => (
                  <div key={status} className="flex items-center gap-2">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ backgroundColor: STATUS_COLORS[status] || "#6b7280" }}
                    />
                    <StatusBadge status={status} />
                    <span className="font-mono text-sm">{count as number}</span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Documentos por tipo</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-6">
              <ResponsiveContainer width={120} height={120}>
                <PieChart>
                  <Pie
                    data={Object.entries(data.documents.by_type).map(([name, value]) => ({
                      name,
                      value,
                    }))}
                    cx="50%"
                    cy="50%"
                    innerRadius={30}
                    outerRadius={50}
                    paddingAngle={2}
                    dataKey="value"
                  >
                    {Object.entries(data.documents.by_type).map(([type], index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={CHART_COLORS[index % CHART_COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-2">
                {Object.entries(data.documents.by_type).map(([type, count], index) => (
                  <div key={type} className="flex items-center gap-2">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{
                        backgroundColor: CHART_COLORS[index % CHART_COLORS.length],
                      }}
                    />
                    <span className="text-sm capitalize">{type}</span>
                    <span className="font-mono text-sm">{count as number}</span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Stats Row */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Confianza OCR</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {Math.round(data.documents.avg_ocr_confidence * 100)}%
            </div>
            <p className="text-xs text-muted-foreground">
              Promedio en todas las páginas
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Tiempo de procesamiento</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {data.processing.avg_processing_time_seconds.toFixed(1)}s
            </div>
            <p className="text-xs text-muted-foreground">Promedio por documento hoy</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm flex items-center gap-2">
              <HardDrive className="h-4 w-4" />
              Almacenamiento
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {formatBytes(data.documents.total_size_bytes)}
            </div>
            <p className="text-xs text-muted-foreground">Total archivos</p>
          </CardContent>
        </Card>
      </div>

      {/* Workers Status */}
      {workersData && workersData.workers.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Workers Celery</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {workersData.workers.map((worker: any) => (
                <div key={worker.name} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                    <span className="text-sm font-mono">{worker.name}</span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-muted-foreground">
                    <span>PID {worker.pid}</span>
                    <span>{worker.active_tasks} tareas activas</span>
                    <span>{worker.pool_processes} procesos</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

async function request(path: string) {
  const base = import.meta.env.VITE_API_BASE_URL || "/api/v1"
  const res = await fetch(`${base}${path}`, { credentials: "include" })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
