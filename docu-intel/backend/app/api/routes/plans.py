from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, delete, select
from sqlalchemy.orm import Session

from app.ai.local_client import LocalVisionClient
from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.database.session import get_db
from app.models import Document, Plan, PlanCadEntity, PlanDimension, PlanRoom, PlanSymbol, User
from app.schemas.business import (
    PlanBulkUpdate,
    PlanCadEntityRead,
    PlanDimensionCreate,
    PlanDimensionRead,
    PlanRead,
    PlanRoomCreate,
    PlanRoomRead,
    PlanRoomUpdate,
    PlanScaleUpdate,
    PlanSymbolRead,
    PlanSymbolSummary,
    PlanVisionSuggestion,
    PlanVisionSuggestionRequest,
    PlanVisionSuggestionResponse,
)
from app.services.audit import write_audit
from app.services.search_service import _escape_ilike_wildcards
from app.services.tenant_access import filter_records_by_document_scope, resolve_user_access_scope
from app.services.vision_manager import VisionManager

router = APIRouter()
rooms_router = APIRouter()
logger = logging.getLogger("app.api.routes.plans")


@router.get("", response_model=list[PlanRead])
def list_plans(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(Plan).order_by(Plan.created_at.desc())
    scope = resolve_user_access_scope(db, user)
    if scope.is_admin:
        return list(db.scalars(stmt.limit(limit)).all())
    candidates = list(db.scalars(stmt.limit(max(limit * 5, 200))).all())
    return filter_records_by_document_scope(db, candidates, scope)[:limit]


@router.get("/{plan_id}", response_model=PlanRead)
def get_plan(
    plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> Plan:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.get("/{plan_id}/rooms", response_model=list[PlanRoomRead])
def get_rooms(
    plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[PlanRoom]:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")
    return list(db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan_id)).all())


@router.get("/{plan_id}/dimensions", response_model=list[PlanDimensionRead])
def get_dimensions(
    plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[PlanDimension]:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")
    return list(db.scalars(select(PlanDimension).where(PlanDimension.plan_id == plan_id)).all())


@router.get("/{plan_id}/cad-entities", response_model=list[PlanCadEntityRead])
def get_cad_entities(
    plan_id: int,
    entity_type: str | None = Query(default=None),
    layer: str | None = Query(default=None),
    layout: str | None = Query(default=None),
    text: str | None = Query(default=None, min_length=1, max_length=120),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PlanCadEntity]:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")
    stmt = select(PlanCadEntity).where(PlanCadEntity.plan_id == plan_id)
    if entity_type:
        stmt = stmt.where(PlanCadEntity.entity_type == entity_type)
    if layer:
        stmt = stmt.where(PlanCadEntity.layer == layer)
    if layout:
        stmt = stmt.where(PlanCadEntity.layout == layout)
    if text:
        pattern = f"%{_escape_ilike_wildcards(text)}%"
        stmt = stmt.where(cast(PlanCadEntity.properties_json, String).ilike(pattern))
    return list(db.scalars(stmt.order_by(PlanCadEntity.id.asc()).offset(offset).limit(limit)).all())


# P2 — Plan symbol detection (YOLOv8). The endpoints return what
# ``persist_plan_extraction`` already wrote to the ``plan_symbols``
# table. Two flavours are exposed:
#   - ``GET /plans/{id}/symbols``        → full list (one row per detection)
#   - ``GET /plans/{id}/symbols/summary`` → counts per class (cheap payload)
# The summary endpoint is what the frontend uses to render the side
# panel; the full list is for the plan canvas overlay.


@router.get("/{plan_id}/symbols", response_model=list[PlanSymbolRead])
def get_plan_symbols(
    plan_id: int,
    symbol_class: str | None = Query(
        default=None, description="Filter to a single symbol class (e.g. ``door``)."
    ),
    min_confidence: float = Query(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Drop detections with confidence below this threshold.",
    ),
    page_number: int | None = Query(
        default=None, ge=1, description="Restrict to a single plan page."
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PlanSymbol]:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")
    stmt = select(PlanSymbol).where(PlanSymbol.plan_id == plan_id)
    if symbol_class:
        stmt = stmt.where(PlanSymbol.symbol_class == symbol_class)
    if min_confidence > 0:
        stmt = stmt.where(PlanSymbol.confidence >= min_confidence)
    if page_number is not None:
        stmt = stmt.where(PlanSymbol.page_number == page_number)
    stmt = stmt.order_by(PlanSymbol.page_number.asc().nullslast(), PlanSymbol.id.asc())
    return list(db.scalars(stmt).all())


@router.get("/{plan_id}/symbols/summary", response_model=PlanSymbolSummary)
def get_plan_symbols_summary(
    plan_id: int,
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PlanSymbolSummary:
    """Return the per-class symbol counts and total for a plan.

    The summary is computed on the fly (a single ``GROUP BY`` query
    would be marginal optimisation) so the endpoint stays correct
    even after the operator changes the YOLO model and re-runs the
    pipeline.
    """
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")
    stmt = select(PlanSymbol).where(PlanSymbol.plan_id == plan_id)
    if min_confidence > 0:
        stmt = stmt.where(PlanSymbol.confidence >= min_confidence)
    rows = list(db.scalars(stmt).all())
    counts: dict[str, int] = {}
    source_model: str | None = None
    for sym in rows:
        counts[sym.symbol_class] = counts.get(sym.symbol_class, 0) + 1
        if source_model is None:
            source_model = sym.source_model
    return PlanSymbolSummary(
        plan_id=plan_id,
        counts=counts,
        total=sum(counts.values()),
        source_model=source_model,
    )


@router.patch("/{plan_id}/scale", response_model=PlanRead)
def update_scale(
    plan_id: int,
    payload: PlanScaleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
) -> Plan:
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
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
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
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
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
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
    write_audit(
        db,
        user=user,
        action="plan_room_created",
        entity_type="plan_room",
        entity_id=plan_id,
        details={"source": room.source},
    )
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
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan room not found")
    write_audit(
        db, user=user, action="plan_room_deleted", entity_type="plan_room", entity_id=room_id
    )
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
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
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
        source_method="manual",
        native_value=payload.value,
        native_unit=payload.unit,
        unit_source="manual",
        validation_status="confirmed",
        needs_review=False,
    )
    db.add(dim)
    write_audit(
        db,
        user=user,
        action="plan_dimension_created",
        entity_type="plan_dimension",
        entity_id=plan_id,
    )
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
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan dimension not found")
    write_audit(
        db,
        user=user,
        action="plan_dimension_deleted",
        entity_type="plan_dimension",
        entity_id=dim_id,
    )
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
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("rooms") is not None:
        db.execute(delete(PlanRoom).where(PlanRoom.plan_id == plan_id))
        for r in data["rooms"]:
            if not r:
                continue
            db.add(
                PlanRoom(
                    plan_id=plan_id,
                    name=(r.get("name") or "").strip() or None,
                    area_m2=r.get("area_m2"),
                    width_m=r.get("width_m"),
                    length_m=r.get("length_m"),
                    polygon_json=r.get("polygon_json"),
                    confidence=r.get("confidence") or 0.95,
                    source=r.get("source") or "manual",
                    needs_review=bool(r.get("needs_review")),
                )
            )
    if data.get("dimensions") is not None:
        # The annotation editor owns only manual rows. Native CAD and OCR
        # dimensions remain source evidence and must survive a canvas save.
        db.execute(
            delete(PlanDimension)
            .where(PlanDimension.plan_id == plan_id)
            .where(PlanDimension.source_method == "manual")
        )
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
            db.add(
                PlanDimension(
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
                    source_method="manual",
                    native_value=d.get("value"),
                    native_unit=d.get("unit"),
                    unit_source="manual",
                    validation_status="confirmed",
                    needs_review=False,
                )
            )
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
    write_audit(
        db,
        user=user,
        action="plan_bulk_update",
        entity_type="plan",
        entity_id=plan_id,
        details={
            "rooms": len(data.get("rooms") or []),
            "dimensions": len(data.get("dimensions") or []),
        },
    )
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
    "    ...\n"
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
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")
    document = db.get(Document, plan.document_id)
    if not document or not document.stored_filename:
        return PlanVisionSuggestionResponse(
            rooms=[], model=settings.vision_model_structured or settings.vision_model or None
        )
    pdf_path = Path(settings.files_dir) / document.stored_filename
    if not pdf_path.exists() and document.source_path:
        pdf_path = Path(document.source_path)
    if not pdf_path.exists():
        return PlanVisionSuggestionResponse(
            rooms=[], model=settings.vision_model_structured or settings.vision_model or None
        )

    # Ensure the vision model is loaded (on-demand). For structured-
    # output tasks we use the non-thinking variant (``qwen/qwen3-vl-8b``)
    # because the thinking variant exhausts the token budget on
    # chain-of-thought and returns empty content.
    structured_model = settings.vision_model_structured or settings.vision_model
    target_model = structured_model or settings.vision_model

    # Make sure the right model is loaded.
    if target_model:
        try:
            from app.services.vision_manager import VisionManager as _VM

            if not _VM.is_loaded(target_model):
                # If a different vision model is loaded, swap by loading
                # the desired one (lms keeps the previous around for a
                # moment, but if memory is tight the user can unload
                # the other explicitly).
                _VM.ensure_loaded(target_model)
        except Exception:
            logger.debug("vision_model_load_failed", exc_info=True)

    # Non-thinking variant for JSON output.
    client = LocalVisionClient(use_structured_model=True)
    # The vision call is async, but this endpoint runs inside the
    # FastAPI event loop, so we cannot ``await`` it directly. Run the
    # coroutine in a worker thread with a fresh event loop instead.
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_run_plan_vision_sync, client, pdf_path, payload.page_number)
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
            project_name = data.get("project_name") or None
            scale_text = data.get("scale_text") or None
            for r in data.get("rooms") or []:
                bbox = r.get("bbox") or []
                if not isinstance(bbox, list) or len(bbox) != 4:
                    continue
                name = (r.get("name") or "").strip()
                if not name:
                    continue
                try:
                    suggestions.append(
                        PlanVisionSuggestion(
                            name=name[:120],
                            bbox=[float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
                            confidence=float(r.get("confidence") or 0.6)
                            if r.get("confidence") is not None
                            else 0.6,
                            rationale=(r.get("rationale") or None),
                        )
                    )
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

        with NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
            pix.save(tmp_file.name)
        tmp = Path(tmp_file.name)
    try:
        # Qwen3-VL is a "thinking" model: it spends a lot of tokens
        # reasoning before the final answer. We need max_tokens high
        # enough to leave room for the actual JSON response after
        # the reasoning chain. 8000 leaves ~6k of headroom for
        # thinking + ~2k for the JSON body.
        return await client.describe(tmp, prompt=_VISION_PROMPT, max_tokens=8000)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


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
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan room not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, field, value)
    write_audit(
        db, user=user, action="plan_room_updated", entity_type="plan_room", entity_id=room.id
    )
    db.commit()
    db.refresh(room)
    return room


# ===========================================================================
# PM7 — Overlays, confirmation, and learning
# ===========================================================================


class OverlayRegion(BaseModel):
    """A labeled region on the plan (cajetín, legend, etc.)."""

    region_type: str  # "cajetin", "legend", "notes", "revision_table", "viewport"
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in PDF coords
    label: str
    confidence: float = 1.0
    page_number: int = 1
    source_document: str = ""
    source_kind: str = "derived"


def _cad_dimension_overlay_bbox(
    plan: Plan,
    coordinates: dict | None,
) -> tuple[float, float, float, float] | None:
    """Map persisted native CAD coordinates to the cached preview canvas."""
    transform = plan.coordinate_transform_json or {}
    extents = transform.get("extents") or plan.cad_extents_json or {}
    try:
        x1, y1 = float(extents["x1"]), float(extents["y1"])
        x2, y2 = float(extents["x2"]), float(extents["y2"])
    except (KeyError, TypeError, ValueError):
        return None
    points = list((coordinates or {}).get("definition_points") or [])
    text_point = (coordinates or {}).get("text_point")
    if isinstance(text_point, (list, tuple)):
        points.append(text_point)
    parsed: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            parsed.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            continue
    if not parsed:
        return None
    width = float(transform.get("canvas_width") or 1400)
    height = float(transform.get("canvas_height") or 1000)
    margin = float(transform.get("margin") or 50)
    scale = transform.get("scale")
    if not isinstance(scale, (int, float)):
        scale = min(
            (width - 2 * margin) / max(x2 - x1, 1e-9),
            (height - 2 * margin) / max(y2 - y1, 1e-9),
        )

    def project(point: tuple[float, float]) -> tuple[float, float]:
        return (
            (margin + (point[0] - x1) * float(scale)) / width,
            (height - margin - (point[1] - y1) * float(scale)) / height,
        )

    projected = [project(point) for point in parsed]
    xs = [point[0] for point in projected]
    ys = [point[1] for point in projected]
    padding = 0.012
    return (
        max(0.0, min(xs) - padding),
        max(0.0, min(ys) - padding),
        min(1.0, max(xs) + padding),
        min(1.0, max(ys) + padding),
    )


class ChatFactOverlay(BaseModel):
    """A fact cited by chat that should be highlighted on the plan."""

    fact_type: str  # "room", "dimension", "symbol", "material"
    subject: str
    value: str
    bbox: tuple[float, float, float, float] | None = None
    page_number: int = 1
    source_document: str = ""
    confidence: float = 0.0


class RevisionChange(BaseModel):
    """A change between two revisions of the same plan."""

    change_type: str  # "added", "removed", "modified"
    entity_type: str  # "room", "dimension", "symbol", "text"
    description: str
    bbox_old: tuple[float, float, float, float] | None = None
    bbox_new: tuple[float, float, float, float] | None = None
    page_number: int = 1


class ConfirmRequest(BaseModel):
    """Request to confirm/reject an entity."""

    action: str  # "confirm" | "reject"
    notes: str | None = None


class CorrectRoomRequest(BaseModel):
    """Request to correct a room's name or polygon."""

    name: str | None = None
    polygon: list[dict] | None = None  # [{"x": 0, "y": 0}, ...]
    notes: str | None = None


class ScaleCalibrationRequest(BaseModel):
    """Request to calibrate scale with two points."""

    point1: dict  # {"x": 0, "y": 0}
    point2: dict  # {"x": 100, "y": 0}
    real_distance_m: float


@router.get("/{plan_id}/overlays", response_model=list[OverlayRegion])
def get_plan_overlays(
    plan_id: int,
    page: int | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """PM7.1 — Get overlay regions for a plan (cajetín, legend, notes)."""
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")

    document = db.get(Document, plan.document_id)
    source_document = document.original_filename if document else ""
    # A title-block indicator has no geometry extractor yet, so keep it
    # explicitly marked as derived. Room and dimension overlays below are
    # source-backed facts with their persisted confidence and coordinates.
    regions = [
        OverlayRegion(
            region_type="cajetin",
            bbox=(0.05, 0.85, 0.35, 0.95),
            label=f"{plan.project_name or 'Proyecto'} - {plan.project_phase or ''}",
            confidence=0.9,
            source_document=source_document,
            source_kind="plan_metadata",
        ),
    ]

    for dimension in db.scalars(
        select(PlanDimension).where(PlanDimension.plan_id == plan_id)
    ).all():
        coordinates = (dimension.bbox_x1, dimension.bbox_y1, dimension.bbox_x2, dimension.bbox_y2)
        source_kind = "ocr_dimension"
        if any(value is None for value in coordinates):
            cad_bbox = _cad_dimension_overlay_bbox(plan, dimension.coordinates_json)
            if cad_bbox is None:
                continue
            coordinates = cad_bbox
            source_kind = "cad_dimension"
        regions.append(
            OverlayRegion(
                region_type="dimension",
                bbox=coordinates,
                label=dimension.raw_text or str(dimension.value_m or dimension.value or "Cota"),
                confidence=dimension.confidence or 0.0,
                page_number=dimension.page_number or 1,
                source_document=source_document,
                source_kind=source_kind,
            )
        )

    for room in db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan_id)).all():
        points = room.polygon_json if isinstance(room.polygon_json, list) else []
        coordinates = [
            (point.get("x"), point.get("y")) for point in points if isinstance(point, dict)
        ]
        coordinates = [(x, y) for x, y in coordinates if x is not None and y is not None]
        if not coordinates:
            continue
        xs = [point[0] for point in coordinates]
        ys = [point[1] for point in coordinates]
        regions.append(
            OverlayRegion(
                region_type="room",
                bbox=(min(xs), min(ys), max(xs), max(ys)),
                label=room.name or "Estancia",
                confidence=room.confidence or 0.0,
                source_document=source_document,
                source_kind=room.source or "ocr_room",
            )
        )

    if page:
        regions = [r for r in regions if r.page_number == page]

    return regions


@router.get("/{plan_id}/chat-facts", response_model=list[ChatFactOverlay])
def get_plan_chat_facts(
    plan_id: int,
    query: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """PM7.1 — Get chat-cited facts to highlight on the plan."""
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")

    facts: list[ChatFactOverlay] = []

    # Add room facts
    rooms = list(db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan_id)).all())
    for room in rooms:
        if room.polygon_json:
            # Estimate bbox from polygon
            points = room.polygon_json if isinstance(room.polygon_json, list) else []
            if points:
                xs = [p.get("x", 0) for p in points if isinstance(p, dict)]
                ys = [p.get("y", 0) for p in points if isinstance(p, dict)]
                if xs and ys:
                    facts.append(
                        ChatFactOverlay(
                            fact_type="room",
                            subject=room.name or "Sin nombre",
                            value=f"{room.area_m2:.1f} m²" if room.area_m2 else "",
                            bbox=(min(xs), min(ys), max(xs), max(ys)),
                            confidence=room.confidence or 0.8,
                        )
                    )

    # Filter by query if provided
    if query:
        query_lower = query.lower()
        facts = [
            f for f in facts if query_lower in f.subject.lower() or query_lower in f.value.lower()
        ]

    return facts


@router.get("/{plan_id}/revisions", response_model=list[RevisionChange])
def get_plan_revision_changes(
    plan_id: int,
    revision_a: str | None = Query(None),
    revision_b: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """PM5.3 — Get changes between two revisions of the same plan."""
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")

    # For now, return empty list — revision comparison requires
    # two versions of the same plan stored in the database
    return []


@router.post("/{plan_id}/rooms/{room_id}/confirm", response_model=PlanRoomRead)
def confirm_room(
    plan_id: int,
    room_id: int,
    payload: ConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    """PM7.2 — Confirm or reject a detected room."""
    room = db.get(PlanRoom, room_id)
    if not room or room.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Room not found")

    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")

    if payload.action == "confirm":
        room.needs_review = False
        room.confidence = min(1.0, (room.confidence or 0.5) + 0.2)
    elif payload.action == "reject":
        room.needs_review = True
        room.confidence = max(0.0, (room.confidence or 0.5) - 0.3)

    write_audit(
        db,
        user=user,
        action=f"plan_room_{payload.action}ed",
        entity_type="plan_room",
        entity_id=room_id,
    )
    db.commit()
    db.refresh(room)
    return room


@router.patch("/{plan_id}/rooms/{room_id}", response_model=PlanRoomRead)
def correct_room(
    plan_id: int,
    room_id: int,
    payload: CorrectRoomRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    """PM7.2 — Correct a room's name or polygon."""
    room = db.get(PlanRoom, room_id)
    if not room or room.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Room not found")

    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")

    if payload.name is not None:
        room.name = payload.name
    if payload.polygon is not None:
        room.polygon_json = payload.polygon
    room.needs_review = False
    room.confidence = min(1.0, (room.confidence or 0.5) + 0.3)

    write_audit(
        db,
        user=user,
        action="plan_room_corrected",
        entity_type="plan_room",
        entity_id=room_id,
    )
    db.commit()
    db.refresh(room)
    return room


@router.post("/{plan_id}/confirm-scale", response_model=PlanRead)
def confirm_scale(
    plan_id: int,
    payload: ScaleCalibrationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    """PM7.2 — Calibrate scale using two points and a known real distance."""
    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")

    import math

    dx = payload.point2["x"] - payload.point1["x"]
    dy = payload.point2["y"] - payload.point1["y"]
    pixel_distance = math.sqrt(dx * dx + dy * dy)

    if pixel_distance > 0 and payload.real_distance_m > 0:
        # Calculate scale: pixels per meter
        pixels_per_meter = pixel_distance / payload.real_distance_m
        # Convert to ratio (assuming 72 DPI PDF)
        scale_ratio = int(72 / (pixels_per_meter / 25.4 * 72))

        plan.scale_ratio = scale_ratio
        plan.scale_text = f"1:{scale_ratio}"
        plan.has_valid_scale = True
        plan.scale_confidence = 1.0

    write_audit(
        db,
        user=user,
        action="plan_scale_calibrated",
        entity_type="plan",
        entity_id=plan_id,
    )
    db.commit()
    db.refresh(plan)
    return plan


@router.post("/{plan_id}/dimensions/{dim_id}/confirm", response_model=PlanDimensionRead)
def confirm_dimension(
    plan_id: int,
    dim_id: int,
    payload: ConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "gestor")),
):
    """PM7.2 — Confirm or reject a detected dimension."""
    dim = db.get(PlanDimension, dim_id)
    if not dim or dim.plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Dimension not found")

    plan = db.get(Plan, plan_id)
    if not plan or plan not in filter_records_by_document_scope(
        db, [plan], resolve_user_access_scope(db, user)
    ):
        raise HTTPException(status_code=404, detail="Plan not found")

    if payload.action == "confirm":
        dim.confidence = min(1.0, (dim.confidence or 0.5) + 0.2)
        dim.validation_status = "confirmed"
        dim.needs_review = False
    elif payload.action == "reject":
        dim.confidence = max(0.0, (dim.confidence or 0.5) - 0.3)
        dim.validation_status = "rejected"
        dim.needs_review = False

    write_audit(
        db,
        user=user,
        action=f"plan_dimension_{payload.action}ed",
        entity_type="plan_dimension",
        entity_id=dim_id,
    )
    db.commit()
    db.refresh(dim)
    return dim
