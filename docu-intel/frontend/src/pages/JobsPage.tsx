import { useQuery } from "@tanstack/react-query"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { StatusBadge } from "@/components/layout/StatusBadge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatDate } from "@/lib/utils"

export function JobsPage() {
  const { data } = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 5000 })

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
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  )
}

