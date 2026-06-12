import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Breadcrumbs } from "@/components/layout/Breadcrumbs"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { formatDate } from "@/lib/utils"

import {
  useOcrFlowDocument,
  useOcrFlowLive,
} from "./useAdminOcrFlowData"

const STEP_LABELS: Record<string, string> = {
  "watcher.detected": "Detectado en watcher",
  "ingestion.committed": "Ingerido en BD",
  "extraction_job": "Job de extracción",
  "page.processed": "Página procesada",
}

const ENGINE_LABELS: Record<string, string> = {
  paddleocr: "PaddleOCR",
  pymupdf: "PyMuPDF",
  tesseract: "Tesseract",
  pp_structure: "PP-Structure",
  ppstructure: "PP-Structure",
  vlm_ocr: "VLM",
  vlm: "VLM",
  empty: "Sin OCR",
  dotsmocr: "Dots MOCR",
}

function engineLabel(tier: string): string {
  return ENGINE_LABELS[tier] ?? tier
}

interface CascadeAttemptLike {
  id: number
  tier: string
  tier_index: number
  success: boolean
  duration_ms: number
  confidence: number | null
  reason: string | null
  error_message: string | null
}

export function AdminOcrFlowTab() {
  const [activeDocumentId, setActiveDocumentId] = useState<number | null>(null)
  const live = useOcrFlowLive()
  const docFlow = useOcrFlowDocument(activeDocumentId)
  const jobs = live.data?.jobs ?? []

  return (
    <>
      <Breadcrumbs items={[{ label: "Administración" }, { label: "Flujo OCR" }]} />
      <PageHeader
        title="Flujo OCR"
        description="Visualización en directo y por documento del recorrido de cada archivo por el pipeline."
      />

      <Tabs defaultValue="live">
        <TabsList>
          <TabsTrigger value="live">En directo</TabsTrigger>
          <TabsTrigger value="document">Por documento</TabsTrigger>
        </TabsList>

        <TabsContent value="live" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Jobs activos</CardTitle>
              <CardDescription>
                {jobs.length} job(s) en cola o ejecución. Se actualiza vía SSE.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Documento</TableHead>
                    <TableHead>Tipo</TableHead>
                    <TableHead>Estado</TableHead>
                    <TableHead>Inicio</TableHead>
                    <TableHead>Reintentos</TableHead>
                    <TableHead className="text-right">Acción</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.map((job) => (
                    <TableRow
                      key={`${job.job_id}-${job.document_id}`}
                    >
                      <TableCell className="font-medium">
                        {job.original_filename}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{job.job_type}</Badge>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={job.status} />
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">
                        {job.started_at ? formatDate(job.started_at) : "—"}
                      </TableCell>
                      <TableCell>{job.retries}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setActiveDocumentId(job.document_id)}
                        >
                          Ver flujo
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!jobs.length ? (
                    <TableRow>
                      <TableCell
                        className="h-24 text-center text-muted-foreground"
                        colSpan={6}
                      >
                        No hay jobs en ejecución. Sube un documento o espera a
                        que el watcher detecte uno nuevo.
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="document" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Flujo del documento</CardTitle>
              <CardDescription>
                {activeDocumentId
                  ? `Línea de tiempo histórica del documento #${activeDocumentId}.`
                  : "Selecciona un documento desde la pestaña 'En directo' para ver su línea de tiempo."}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!activeDocumentId ? (
                <p className="text-sm text-muted-foreground">
                  Sin documento seleccionado.
                </p>
              ) : (
                <ol className="space-y-3">
                  {(docFlow.data?.steps ?? []).map((step, idx) => {
                    const cascade = Array.isArray(
                      (step.details as { cascade_attempts?: unknown[] })
                        .cascade_attempts,
                    )
                      ? ((step.details as { cascade_attempts: CascadeAttemptLike[] })
                          .cascade_attempts)
                      : []
                    return (
                      <li
                        className="rounded-md border p-3"
                        key={`${step.kind}-${idx}`}
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold">
                            {STEP_LABELS[step.kind] ?? step.kind}
                          </span>
                          {step.kind === "page.processed" &&
                          step.details.ocr_engine ? (
                            <Badge variant="outline">
                              {engineLabel(String(step.details.ocr_engine))}
                            </Badge>
                          ) : null}
                          {typeof step.details.ocr_confidence === "number" ? (
                            <Badge variant="secondary">
                              {Math.round(
                                Number(step.details.ocr_confidence) * 100,
                              )}
                              % confianza
                            </Badge>
                          ) : null}
                          <span className="text-muted-foreground ml-auto text-xs">
                            {step.at ? formatDate(step.at) : "—"}
                          </span>
                        </div>

                        {cascade.length > 0 ? (
                          <ol className="mt-2 space-y-1 border-l-2 pl-3 text-xs">
                            {cascade.map((attempt) => {
                              const dur = Number(attempt.duration_ms ?? 0)
                              const ok = Boolean(attempt.success)
                              const conf =
                                typeof attempt.confidence === "number"
                                  ? Math.round(Number(attempt.confidence) * 100)
                                  : null
                              return (
                                <li
                                  className="flex flex-wrap items-center gap-2"
                                  key={String(attempt.id)}
                                >
                                  <span className="text-muted-foreground font-mono">
                                    T{Number(attempt.tier_index)}
                                  </span>
                                  <span className="font-medium">
                                    {engineLabel(String(attempt.tier))}
                                  </span>
                                  <Badge
                                    variant={ok ? "success" : "destructive"}
                                  >
                                    {ok ? "✓" : "✗"} {dur} ms
                                  </Badge>
                                  {conf !== null ? (
                                    <span className="text-muted-foreground">
                                      {conf}% conf
                                    </span>
                                  ) : null}
                                  {attempt.reason && attempt.reason !== "ok" ? (
                                    <span className="text-muted-foreground">
                                      · {String(attempt.reason)}
                                    </span>
                                  ) : null}
                                  {attempt.error_message ? (
                                    <span className="text-destructive">
                                      · {String(attempt.error_message)}
                                    </span>
                                  ) : null}
                                </li>
                              )
                            })}
                          </ol>
                        ) : null}

                        {step.error ? (
                          <p className="text-destructive mt-2 text-sm">
                            Error: {step.error}
                          </p>
                        ) : null}
                      </li>
                    )
                  })}
                </ol>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </>
  )
}
