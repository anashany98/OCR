import { Link, useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, Loader2, Save, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

import {
  AnnotationEditor,
  AnnotationSidebar,
  Breadcrumbs,
  CanvasToolbar,
  PlanCanvas,
} from "./plano/components"
import { usePlanAnnotation } from "./plano/usePlanAnnotation"

// ---------------------------------------------------------------------------
// F8b-cont - plano annotation page composition
//
// The previous file was 37 KB / 945 lines mixing data fetching, local
// state for rooms/dimensions, canvas interaction (SVG hit testing,
// polygon building, dimension/scale capture), vision-assisted
// suggestions, scale computation, save logic, and a large render
// function with three layout regions (sidebar, canvas, editor).
//
// After F8b-cont:
// - usePlanAnnotation() owns every piece of state and side effect
//   (queries, drafts, tool selection, canvas handlers, scale, save);
// - AnnotationSidebar renders the left room/dimension lists;
// - PlanCanvas renders the SVG and its toolbar;
// - AnnotationEditor renders the right panel (project name, scale,
//   selected-room editor, shortcuts);
// - this file is just the layout shell: top bar, three-column grid,
//   loading / empty / error states.
// ---------------------------------------------------------------------------
export function PlanoAnnotationPage() {
  const { id } = useParams<{ id: string }>()
  const documentId = Number(id)
  const navigate = useNavigate()
  const a = usePlanAnnotation(documentId)

  if (!a.plan && a.plansList.isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Cargando plano...
      </div>
    )
  }
  if (!a.plan) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <p className="text-sm text-muted-foreground">
          Este documento no está clasificado como plano o no tiene un Plan asociado.
        </p>
        <Link
          to={`/documents/${documentId}`}
          className="text-[12px] text-[var(--accent)] underline"
        >
          Volver al documento
        </Link>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Breadcrumbs items={[{ label: "Anotar plano" }]} />

      {/* Top bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--bg-surface)] px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/documents/${documentId}`)}
            className="gap-1.5"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> Volver
          </Button>
          <div className="ml-1 flex flex-col">
            <span className="text-[12.5px] font-semibold text-[var(--text-primary)]">
              Plano #{a.plan.id} · doc #{a.plan.document_id}
            </span>
            <span className="text-[11px] text-[var(--text-muted)]">
              {a.plan.project_name || "Sin nombre de proyecto"} ·{" "}
              {a.plan.has_valid_scale ? `escala 1:${a.plan.scale_ratio}` : "sin escala"}
              {a.dirty ? " · cambios sin guardar" : ""}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={a.suggest}
            disabled={a.suggesting}
            className="gap-1.5"
          >
            {a.suggesting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Sugerir con IA
          </Button>
          <Button
            size="sm"
            onClick={a.onSave}
            disabled={a.saving || !a.dirty}
            className="gap-1.5"
          >
            {a.saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            Guardar
          </Button>
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 sm:p-4 lg:grid-cols-[280px_minmax(0,1fr)_300px]">
        {/* LEFT: rooms + dimensions */}
        <Card className="flex min-h-0 flex-col overflow-hidden">
          <CardContent className="flex min-h-0 flex-1 flex-col gap-0 p-0">
            <AnnotationSidebar
              rooms={a.rooms}
              dimensions={a.dimensions}
              selectedId={a.selectedId}
              setSelectedId={a.setSelectedId}
            />
          </CardContent>
        </Card>

        {/* CENTER: canvas */}
        <Card className="flex min-h-0 flex-col overflow-hidden">
          <CardContent className="flex min-h-0 flex-1 flex-col gap-0 p-0">
            <CanvasToolbar
              tool={a.tool}
              setTool={a.setTool}
              page={a.page}
              setPage={a.setPage}
            />
            <PlanCanvas
              documentId={documentId}
              page={a.page}
              tool={a.tool}
              rooms={a.rooms}
              dimensions={a.dimensions}
              polygonInProgress={a.polygonInProgress}
              draftDim={a.draftDim}
              selectedId={a.selectedId}
              setSelectedId={a.setSelectedId}
              setTool={a.setTool}
              onCanvasClick={a.onCanvasClick}
              onCanvasDoubleClick={a.onCanvasDoubleClick}
              svgRef={a.svgRef}
            />
          </CardContent>
        </Card>

        {/* RIGHT: editor */}
        <Card className="flex min-h-0 flex-col overflow-hidden">
          <CardContent className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
            <AnnotationEditor
              plan={a.plan}
              setProjectName={a.setProjectName}
              scaleDimension={a.scaleDimension}
              scaleLengthM={a.scaleLengthM}
              setScaleLengthM={a.setScaleLengthM}
              scaleRatio={a.scaleRatio}
              selected={a.selected}
              updateSelected={a.updateSelected}
              deleteSelected={a.deleteSelected}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
