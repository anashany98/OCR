import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDate } from "@/lib/utils"

export function JobsPage() {
  const queryClient = useQueryClient()
  const { data } = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 5000 })
  const retryJob = useMutation({
    mutationFn: api.retryJob,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  })
  const cancelJob = useMutation({
    mutationFn: api.cancelJob,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["jobs"] }),
  })

  return (
    <>
      <PageHeader title="Jobs" description="Cola de extracción y reprocesado en Celery." />
      <Card>
        <CardHeader>
          <CardTitle>Últimos trabajos</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Documento</TableHead>
                <TableHead>Tipo</TableHead>
                <TableHead>Estado</TableHead>
                <TableHead>Inicio</TableHead>
                <TableHead>Fin</TableHead>
                <TableHead>Error</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data ?? []).map((job) => (
                <TableRow key={job.id}>
                  <TableCell>{job.id}</TableCell>
                  <TableCell>{job.document_id}</TableCell>
                  <TableCell>{job.job_type}</TableCell>
                  <TableCell>
                    <StatusBadge status={job.status} />
                  </TableCell>
                  <TableCell>{formatDate(job.started_at)}</TableCell>
                  <TableCell>{formatDate(job.finished_at)}</TableCell>
                  <TableCell className="max-w-md truncate">{job.error_message ?? "-"}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button type="button" variant="outline" size="sm" onClick={() => retryJob.mutate(job.id)} disabled={retryJob.isPending}>
                        Reintentar
                      </Button>
                      <Button type="button" variant="outline" size="sm" onClick={() => cancelJob.mutate(job.id)} disabled={cancelJob.isPending || !["pending", "failed"].includes(job.status)}>
                        Cancelar
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  )
}
