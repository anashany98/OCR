from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.local_client import LocalVisionClient
from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.database.session import get_db
from app.models import Document, Plan, PlanDimension, PlanRoom, User
from app.schemas.business import (
    PlanBulkUpdate,
    PlanDimensionCreate,
    PlanDimensionRead,
    PlanRead,
    PlanRoomCreate,
    PlanRoomRead,
    PlanRoomUpdate,
    PlanScaleUpdate,
    PlanVisionSuggestion,
    PlanVisionSuggestionRequest,
    PlanVisionSuggestionResponse,
)
from app.services.audit import write_audit
from app.services.tenant_access import filter_records_by_document_scope, resolve_user_access_scope
from app.services.vision_manager import VisionManager

router = APIRouter()
rooms_router = APIRouter()
logger = logging.getLogger("app.api.routes.plans")


@router.get("", response_model=list[PlanRead])
def list_plans(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Plan).order_by(Plan.created_at.desc())
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        return list(db.scalars(stmt.limit(limit)).all())
    candidates = list(db.scalars(stmt.limit(max(limit * 5, 200))).all())
    return filter_records_by_document_scope(db, candidates, scope)[:limit]


@router.get("/{plan_id}", response_model=PlanRead)
def get_plan(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Plan:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.get("/{plan_id}/rooms", response_model=list[PlanRoomRead])
def get_rooms(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[PlanRoom]:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    return list(db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan_id)).all())


@router.get("/{plan_id}/dimensions", response_model=list[PlanDimensionRead])
def get_dimensions(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[PlanDimension]:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    return list(db.scalars(select(PlanDimension).where(PlanDimension.plan_id == plan_id)).all())


@router.patch("/{plan_id}/scale", response_model=PlanRead)
def update_scale(
    plan_id: int,
    payload: PlanScaleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> Plan:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)
    write_audit(db, user=user, action="plan_scale_updated", entity_type="plan", entity_id=plan.id)
    db.commit()
    db.refresh(plan)
    return plan


@router.patch("/{plan_id}/project", response_model=PlanRead)
def update_project(
    plan_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> Plan:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    name = (payload or {}).get("project_name")
    if name is not None:
        plan.project_name = str(name).strip() or None
    write_audit(db, user=user, action="plan_project_updated", entity_type="plan", entity_id=plan.id)
    db.commit()
    db.refresh(plan)
    return plan


# ---------------------------------------------------------------------------
# Annotation editor endpoints (create / delete + bulk save)
# ---------------------------------------------------------------------------

@router.post("/{plan_id}/rooms", response_model=PlanRoomRead, status_code=201)
def create_room(
    plan_id: int,
    payload: PlanRoomCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> PlanRoom:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    room = PlanRoom(
        plan_id=plan_id,
        name=(payload.name or "").strip() or None,
        area_m2=payload.area_m2,
        width_m=payload.width_m,
        length_m=payload.length_m,
        polygon_json=payload.polygon_json,
        confidence=payload.confidence or 0.95,
        source=payload.source or "manual",
        needs_review=bool(payload.needs_review),
    )
    db.add(room)
    write_audit(db, user=user, action="plan_room_created", entity_type="plan_room", entity_id=plan_id, details={"source": room.source})
    db.commit()
    db.refresh(room)
    return room


@router.delete("/{plan_id}/rooms/{room_id}", status_code=204)
def delete_room(
    plan_id: int,
    room_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    room = db.get(PlanRoom, room_id)
    if not room or room.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Plan room not found")
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan room not found")
    write_audit(db, user=user, action="plan_room_deleted", entity_type="plan_room", entity_id=room_id)
    db.delete(room)
    db.commit()
    return None


@router.post("/{plan_id}/dimensions", response_model=PlanDimensionRead, status_code=201)
def create_dimension(
    plan_id: int,
    payload: PlanDimensionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> PlanDimension:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    # Default value_m: convert value from unit if not provided
    value_m = payload.value_m
    if value_m is None and payload.value is not None:
        if (payload.unit or "m") == "cm":
            value_m = payload.value / 100.0
        elif (payload.unit or "m") == "mm":
            value_m = payload.value / 1000.0
        else:
            value_m = payload.value
    dim = PlanDimension(
        plan_id=plan_id,
        raw_text=payload.raw_text,
        value=payload.value,
        unit=payload.unit,
        value_m=value_m,
        page_number=payload.page_number,
        bbox_x1=payload.bbox_x1,
        bbox_y1=payload.bbox_y1,
        bbox_x2=payload.bbox_x2,
        bbox_y2=payload.bbox_y2,
        confidence=payload.confidence or 0.9,
    )
    db.add(dim)
    write_audit(db, user=user, action="plan_dimension_created", entity_type="plan_dimension", entity_id=plan_id)
    db.commit()
    db.refresh(dim)
    return dim


@router.delete("/{plan_id}/dimensions/{dim_id}", status_code=204)
def delete_dimension(
    plan_id: int,
    dim_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    dim = db.get(PlanDimension, dim_id)
    if not dim or dim.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Plan dimension not found")
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan dimension not found")
    write_audit(db, user=user, action="plan_dimension_deleted", entity_type="plan_dimension", entity_id=dim_id)
    db.delete(dim)
    db.commit()
    return None


@router.put("/{plan_id}/bulk", response_model=PlanRead)
def bulk_update(
    plan_id: int,
    payload: PlanBulkUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> Plan:
    """Replace the working set of rooms and/or dimensions for a plan.

    The client sends the full set it wants to keep; the server wipes
    the existing rows in each requested section and inserts the new
    ones. This makes the editor's save semantics simple: whatever is
    on the canvas IS what ends up in the DB.
    """
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("rooms") is not None:
        db.execute(delete(PlanRoom).where(PlanRoom.plan_id == plan_id))
        for r in data["rooms"]:
            if not r:
                continue
            db.add(PlanRoom(
                plan_id=plan_id,
                name=(r.get("name") or "").strip() or None,
                area_m2=r.get("area_m2"),
                width_m=r.get("width_m"),
                length_m=r.get("length_m"),
                polygon_json=r.get("polygon_json"),
                confidence=r.get("confidence") or 0.95,
                source=r.get("source") or "manual",
                needs_review=bool(r.get("needs_review")),
            ))
    if data.get("dimensions") is not None:
        db.execute(delete(PlanDimension).where(PlanDimension.plan_id == plan_id))
        for d in data["dimensions"]:
            if not d:
                continue
            value_m = d.get("value_m")
            if value_m is None and d.get("value") is not None:
                unit = d.get("unit") or "m"
                if unit == "cm":
                    value_m = d["value"] / 100.0
                elif unit == "mm":
                    value_m = d["value"] / 1000.0
                else:
                    value_m = d["value"]
            db.add(PlanDimension(
                plan_id=plan_id,
                raw_text=d.get("raw_text"),
                value=d.get("value"),
                unit=d.get("unit"),
                value_m=value_m,
                page_number=d.get("page_number"),
                bbox_x1=d.get("bbox_x1"),
                bbox_y1=d.get("bbox_y1"),
                bbox_x2=d.get("bbox_x2"),
                bbox_y2=d.get("bbox_y2"),
                confidence=d.get("confidence") or 0.9,
            ))
    if data.get("scale_text") is not None:
        plan.scale_text = data["scale_text"]
    if data.get("scale_ratio") is not None:
        plan.scale_ratio = data["scale_ratio"]
    if data.get("unit") is not None:
        plan.unit = data["unit"]
    if data.get("has_valid_scale") is not None:
        plan.has_valid_scale = bool(data["has_valid_scale"])
    if data.get("project_name") is not None:
        plan.project_name = (data["project_name"] or "").strip() or None
    write_audit(db, user=user, action="plan_bulk_update", entity_type="plan", entity_id=plan_id, details={"rooms": len(data.get("rooms") or []), "dimensions": len(data.get("dimensions") or [])})
    db.commit()
    db.refresh(plan)
    return plan


# ---------------------------------------------------------------------------
# Vision-assisted suggestions
# ---------------------------------------------------------------------------

_VISION_PROMPT = (
    "Eres un asistente de planificacion de interiores. Analiza este plano "
    "arquitectonico y devuelve UNICAMENTE un JSON valido (sin texto "
    "anterior ni posterior, sin ```markdown, sin ```) con esta forma:\n"
    "{\n"
    '  "project_name": "nombre del proyecto visible o null",\n'
    '  "scale_text": "escala legible en el plano o null",\n'
    '  "rooms": [\n'
    '    {"name": "Salon", "bbox": [x1, y1, x2, y2], "confidence": 0.85, "rationale": "Visible en la esquina inferior izquierda"},\n'
    '    ...\n'
    "  ]\n"
    "}\n\n"
    "Reglas:\n"
    "- bbox en pixeles de la imagen (x1, y1 = esquina superior izquierda; x2, y2 = esquina inferior derecha del rectangulo que envuelve la habitacion)\n"
    "- Solo habitacionES reales (no cuentes armarios sueltos como habitaciones, no incluyas la cota)\n"
    "- Si no lees nada con seguridad, devuelve rooms vacio\n"
    "- maximo 12 habitaciones; si ves mas, quedate con las mas grandes\n"
    "- confidence de 0.0 a 1.0 segun tu certeza\n"
    "- rationale en espanol, 1 frase corta"
)


@router.post("/{plan_id}/suggest-rooms", response_model=PlanVisionSuggestionResponse)
def suggest_rooms(
    plan_id: int,
    payload: PlanVisionSuggestionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> PlanVisionSuggestionResponse:
    """Ask the vision LLM to spot rooms on a specific page of the plano
    and return them as bboxes + names. Best-effort: any failure returns
    an empty suggestion list so the editor can still be used manually.
    """
    import concurrent.futures

    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan not found")
    document = db.get(Document, plan.document_id)
    if not document or not document.stored_filename:
        return PlanVisionSuggestionResponse(rooms=[], model=settings.vision_model_structured or settings.vision_model or None)
    pdf_path = Path(settings.files_dir) / document.stored_filename
    if not pdf_path.exists() and document.source_path:
        pdf_path = Path(document.source_path)
    if not pdf_path.exists():
        return PlanVisionSuggestionResponse(rooms=[], model=settings.vision_model_structured or settings.vision_model or None)

    # Ensure the vision model is loaded (on-demand). For structured-
    # output tasks we use the non-thinking variant (``qwen/qwen3-vl-8b``)
    # because the thinking variant exhausts the token budget on
    # chain-of-thought and returns empty content.
    structured_model = settings.vision_model_structured or settings.vision_model
    target_model = structured_model or settings.vision_model

    # Make sure the right model is loaded.
    if target_model:
        try:
            current = None
            from app.services.vision_manager import VisionManager as _VM
            if not _VM.is_loaded(target_model):
                # If a different vision model is loaded, swap by loading
                # the desired one (lms keeps the previous around for a
                # moment, but if memory is tight the user can unload
                # the other explicitly).
                _VM.ensure_loaded(target_model)
        except Exception:
            pass

    # Non-thinking variant for JSON output.
    client = LocalVisionClient(use_structured_model=True)
    # The vision call is async, but this endpoint runs inside the
    # FastAPI event loop, so we cannot ``await`` it directly. Run the
    # coroutine in a worker thread with a fresh event loop instead.
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(
                _run_plan_vision_sync, client, pdf_path, payload.page_number
            )
            raw = future.result(timeout=settings.vision_timeout_seconds + 30)
    except Exception as exc:
        logger.warning("suggest_rooms vision call failed: %s", exc)
        return PlanVisionSuggestionResponse(rooms=[], model=settings.vision_model or None)
    finally:
        VisionManager.schedule_unload()

    suggestions: list[PlanVisionSuggestion] = []
    project_name: str | None = None
    scale_text: str | None = None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            project_name = (data.get("project_name") or None)
            scale_text = (data.get("scale_text") or None)
            for r in (data.get("rooms") or []):
                bbox = r.get("bbox") or []
                if not isinstance(bbox, list) or len(bbox) != 4:
                    continue
                name = (r.get("name") or "").strip()
                if not name:
                    continue
                try:
                    suggestions.append(PlanVisionSuggestion(
                        name=name[:120],
                        bbox=[float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                        confidence=float(r.get("confidence") or 0.6) if r.get("confidence") is not None else 0.6,
                        rationale=(r.get("rationale") or None),
                    ))
                except (TypeError, ValueError):
                    continue
    except Exception as exc:
        logger.warning("suggest_rooms: vision returned non-JSON: %s", exc)
    return PlanVisionSuggestionResponse(
        project_name=project_name,
        scale_text=scale_text,
        rooms=suggestions[:12],
        model=structured_model or None,
    )


async def _describe_plan_page(client: LocalVisionClient, pdf_path: Path, page_index: int) -> str:
    """Render the requested page to a PNG and call the vision LLM with
    the room-detection prompt."""
    import fitz

    with fitz.open(pdf_path) as pdf:
        if page_index < 0 or page_index >= len(pdf):
            page_index = 0
        page = pdf[page_index]
        zoom = 3.0  # higher zoom so the model can read fine text
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        max_dim = settings.vision_max_image_dim
        if max(pix.width, pix.height) > max_dim:
            scale = max_dim / max(pix.width, pix.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom * scale, zoom * scale), alpha=False)
        from tempfile import NamedTemporaryFile
        tmp = Path(NamedTemporaryFile(suffix=".png", delete=False).name)
        pix.save(str(tmp))
    try:
        # Qwen3-VL is a "thinking" model: it spends a lot of tokens
        # reasoning before the final answer. We need max_tokens high
        # enough to leave room for the actual JSON response after
        # the reasoning chain. 8000 leaves ~6k of headroom for
        # thinking + ~2k for the JSON body.
        return await client.describe(tmp, prompt=_VISION_PROMPT, max_tokens=8000)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _run_plan_vision_sync(client: LocalVisionClient, pdf_path: Path, page_index: int) -> str:
    """Helper that runs the async ``_describe_plan_page`` coroutine in a
    fresh event loop. Used by the sync ``suggest_rooms`` endpoint."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_describe_plan_page(client, pdf_path, page_index))
    finally:
        loop.close()


@rooms_router.patch("/{room_id}", response_model=PlanRoomRead)
def update_room(
    room_id: int,
    payload: PlanRoomUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> PlanRoom:
    room = db.get(PlanRoom, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Plan room not found")
    plan = db.get(Plan, room.plan_id)
    if not plan or plan not in filter_records_by_document_scope(db, [plan], resolve_user_access_scope(db, user)):
        raise HTTPException(status_code=404, detail="Plan room not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, field, value)
    write_audit(db, user=user, action="plan_room_updated", entity_type="plan_room", entity_id=room.id)
    db.commit()
    db.refresh(room)
    return room
