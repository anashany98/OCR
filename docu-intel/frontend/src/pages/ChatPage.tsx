import { FormEvent, useState } from "react"
import { Link } from "react-router-dom"
import { useMutation } from "@tanstack/react-query"
import { Bot, ExternalLink, Send } from "lucide-react"

import { api } from "@/api/client"
import { PageHeader } from "@/components/layout/PageHeader"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import type { AIAnswer } from "@/types/api"

export function ChatPage() {
  const [question, setQuestion] = useState("")
  const [answers, setAnswers] = useState<Array<{ question: string; answer: AIAnswer }>>([])
  const ask = useMutation({
    mutationFn: (value: string) => api.askAI(value),
    onSuccess: (answer, value) => {
      setAnswers((current) => [{ question: value, answer }, ...current])
      setQuestion("")
    },
  })

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const trimmed = question.trim()
    if (trimmed) ask.mutate(trimmed)
  }

  return (
    <>
      <PageHeader title="Chat IA" description="Consulta la base documental mediante herramientas internas controladas y respuestas con fuentes." />
      <Card>
        <CardHeader>
          <CardTitle>Pregunta documental</CardTitle>
          <CardDescription>El modelo local solo recibe contexto recuperado por el backend. No hay SQL libre generado por IA.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex gap-2" onSubmit={onSubmit}>
            <Input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ej. ¿Qué documentos mencionan la referencia ABC123?"
            />
            <Button disabled={!question.trim() || ask.isPending}>
              <Send data-icon="inline-start" />
              Preguntar
            </Button>
          </form>
          {ask.isError ? <p className="mt-3 text-sm text-destructive">{ask.error.message}</p> : null}
        </CardContent>
      </Card>

      {!answers.length ? (
        <Card>
          <CardContent className="flex items-center gap-3 p-4 text-sm text-muted-foreground">
            <Bot />
            <span>Las respuestas aparecerán con datos, fuentes, confianza y advertencias.</span>
          </CardContent>
        </Card>
      ) : null}

      <div className="flex flex-col gap-4">
        {answers.map((item) => (
          <Card key={item.answer.id}>
            <CardHeader>
              <CardTitle className="text-base">{item.question}</CardTitle>
              <CardDescription>
                Modelo: {item.answer.model_name ?? "-"} · Confianza{" "}
                {item.answer.confidence !== null ? `${Math.round(item.answer.confidence * 100)}%` : "-"}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <pre className="whitespace-pre-wrap rounded-md border bg-muted p-4 text-sm leading-6">{item.answer.answer}</pre>
              {item.answer.sources.length ? (
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold">Fuentes</h3>
                  {item.answer.sources.map((source) => (
                    <div key={source.id} className="flex items-start justify-between gap-3 rounded-md border p-3 text-sm">
                      <div>
                        <p className="font-medium">
                          Documento #{source.document_id ?? "-"} · Página {source.page_number ?? "-"}
                        </p>
                        <p className="mt-1 line-clamp-2 text-muted-foreground">{source.excerpt ?? "Sin extracto."}</p>
                      </div>
                      {source.document_id ? (
                        <Button asChild variant="outline" size="sm">
                          <Link to={`/documents/${source.document_id}`}>
                            <ExternalLink data-icon="inline-start" />
                            Abrir
                          </Link>
                        </Button>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  )
}
