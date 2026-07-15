"""PM9 — Technical chat service with RAG and tool calling.

Connects all extraction services to an LLM-powered chat that can
answer construction questions with grounded, sourced responses.

Flow:
  User question → retrieve relevant chunks → build context →
  LLM generates answer with tool calls → format response with sources
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("app.services.technical_chat")


# ---------------------------------------------------------------------------
# Tool definitions for LLM
# ---------------------------------------------------------------------------

TECHNICAL_TOOLS = [
    {
        "name": "get_plan_info",
        "description": "Obtener información general de un plano: escala, fase, revisión, proyecto",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "integer", "description": "ID del plano"},
                "document_id": {"type": "integer", "description": "ID del documento"},
            },
        },
    },
    {
        "name": "get_plan_rooms",
        "description": "Listar habitaciones/estancias de un plano con sus áreas",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "integer", "description": "ID del plano"},
            },
        },
    },
    {
        "name": "get_room_dimensions",
        "description": "Obtener dimensiones de una habitación específica",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "integer", "description": "ID del plano"},
                "room_name": {"type": "string", "description": "Nombre de la habitación"},
            },
            "required": ["room_name"],
        },
    },
    {
        "name": "get_plan_symbols",
        "description": "Contar símbolos (puertas, ventanas, etc.) en un plano",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "integer", "description": "ID del plano"},
                "symbol_class": {"type": "string", "description": "Clase de símbolo a buscar"},
            },
        },
    },
    {
        "name": "get_technical_specs",
        "description": "Obtener especificaciones técnicas de la memoria constructiva",
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {"type": "integer", "description": "ID del documento memoria"},
                "system_element": {"type": "string", "description": "Elemento constructivo a buscar"},
                "material": {"type": "string", "description": "Material a buscar"},
            },
        },
    },
    {
        "name": "find_material_by_room",
        "description": "Buscar qué material se usa en una habitación o zona",
        "parameters": {
            "type": "object",
            "properties": {
                "room_name": {"type": "string", "description": "Nombre de la habitación"},
                "element_type": {"type": "string", "description": "Tipo: tabique, suelo, techo, etc."},
            },
            "required": ["room_name"],
        },
    },
    {
        "name": "get_work_items",
        "description": "Obtener partidas de presupuesto/mediciones",
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {"type": "integer", "description": "ID del documento presupuesto"},
                "chapter": {"type": "string", "description": "Capítulo a filtrar"},
                "room": {"type": "string", "description": "Estancia/zona a filtrar"},
            },
        },
    },
    {
        "name": "aggregate_budget",
        "description": "Agregar partidas por capítulo, unidad o zona",
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {"type": "integer", "description": "ID del documento"},
                "group_by": {"type": "string", "enum": ["chapter", "unit", "zone"], "description": "Agrupar por"},
            },
            "required": ["group_by"],
        },
    },
    {
        "name": "compare_documents",
        "description": "Comparar datos entre plano y memoria para detectar contradicciones",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "integer", "description": "ID del plano"},
                "memory_id": {"type": "integer", "description": "ID de la memoria"},
                "topic": {"type": "string", "description": "Tema a comparar (material, dimensiones, etc.)"},
            },
        },
    },
    {
        "name": "search_technical_text",
        "description": "Buscar texto técnico en documentos (normativa, requisitos, etc.)",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto a buscar"},
                "document_type": {"type": "string", "description": "Filtrar por tipo de documento"},
            },
            "required": ["query"],
        },
    },
]

TOOL_SYSTEM_PROMPT = """Eres un asistente técnico de construcción. Respondes preguntas sobre planos, memorias constructivas, presupuestos y especificaciones técnicas.

REGLAS:
1. SIEMPRE cita la fuente: documento, página, y región cuando sea posible
2. Diferencia entre valores impreso, calculado y manual
3. Si no tienes información, di "No dispongo de esa información en los documentos procesados"
4. Usa las herramientas disponibles para buscar datos específicos
5. Para dimensiones, indica si son impresas (en el plano) o calculadas
6. Para materiales, indica el documento fuente (plano o memoria)
7. Nunca inventes datos técnicos"""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system"
    content: str
    tool_calls: list[dict] | None = None
    tool_results: list[dict] | None = None


@dataclass
class ChatResponse:
    answer: str
    sources: list[ChatSource]
    tool_calls_made: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ChatSource:
    document_id: int | None = None
    document_type: str = ""
    filename: str = ""
    page_number: int | None = None
    section: str = ""
    text_excerpt: str = ""
    bbox: tuple[float, float, float, float] | None = None
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Question classification
# ---------------------------------------------------------------------------

QUESTION_PATTERNS = {
    "scale": re.compile(r"escala|1\s*:\s*\d+", re.IGNORECASE),
    "room": re.compile(r"habitaci[oó]n|estancia|dormitorio|sal[oó]n|cocina|ba[nñ]o|superficie|área|m2|medida", re.IGNORECASE),
    "dimension": re.compile(r"mide|dimensi[oó]n|largo|ancho|alto|cota|metros", re.IGNORECASE),
    "material": re.compile(r"material|tabique|pared|muro|ladrillo|pladur|hormig[oó]n|aislamiento", re.IGNORECASE),
    "fire": re.compile(r"fuego|incendio|REI|resistencia|reacci[oó]n", re.IGNORECASE),
    "acoustic": re.compile(r"ac[uú]stico|ruido|sonido|Rw|dB|aislamiento", re.IGNORECASE),
    "thermal": re.compile(r"t[eé]rmico|calor|U\s*=|transmitancia|EPS|poliestireno", re.IGNORECASE),
    "symbol": re.compile(r"puerta|ventana|s[ií]mbolo|baldosa|sanitario|luminaria", re.IGNORECASE),
    "budget": re.compile(r"presupuesto|partida|medici[oó]n|importe|precio|coste|cuesta|cu[aá]nto vale", re.IGNORECASE),
    "standard": re.compile(r"norma|UNE|enro|c[oó]digo|reglamento|certificaci[oó]n", re.IGNORECASE),
    "comparison": re.compile(r"comparar|diferencia|contradici[oó]n|coincide|cambia", re.IGNORECASE),
}


def classify_question(question: str) -> list[str]:
    """Classify a question into topic categories."""
    topics = []
    for topic, pattern in QUESTION_PATTERNS.items():
        if pattern.search(question):
            topics.append(topic)
    return topics if topics else ["general"]


# ---------------------------------------------------------------------------
# RAG retrieval
# ---------------------------------------------------------------------------

def build_search_queries(question: str) -> list[str]:
    """Build multiple search queries from a user question."""
    queries = [question]

    # Extract key terms
    keywords = re.findall(r"\b[A-Za-záéíóúñ]{4,}\b", question)
    if keywords:
        queries.append(" ".join(keywords[:5]))

    # Add Spanish construction synonyms
    synonym_map = {
        "mide": ["dimensión", "medida", "longitud"],
        "habitación": ["estancia", "local", "espacio"],
        "material": ["composición", "tipo", "elemento"],
        "fuego": ["incendio", "REI", "resistencia"],
    }

    for word, synonyms in synonym_map.items():
        if word in question.lower():
            queries.extend(synonyms[:2])

    return queries[:5]  # Limit to 5 queries


def retrieve_context(
    question: str,
    document_ids: list[int] | None = None,
    max_chunks: int = 10,
) -> list[dict]:
    """Retrieve relevant context chunks for a question.

    In production, this would call the search service.
    For now, returns structured context from extracted data.
    """
    # This is a placeholder that would connect to the actual search service
    # In production: search_service.search_hybrid(question)
    return []


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

def generate_grounded_answer(
    question: str,
    context_chunks: list[dict],
    tool_results: list[dict] | None = None,
) -> ChatResponse:
    """Generate a grounded answer from context and tool results.

    Builds the response by combining retrieved chunks with tool call results.
    """
    sources = []
    answer_parts = []

    # Process context chunks
    for chunk in context_chunks:
        if "text" in chunk:
            answer_parts.append(chunk["text"])
        # Create source from any chunk with document info
        if chunk.get("document_id") or chunk.get("filename") or chunk.get("source"):
            src = ChatSource(
                document_id=chunk.get("document_id"),
                document_type=chunk.get("document_type", ""),
                filename=chunk.get("filename", ""),
                page_number=chunk.get("page_number"),
                section=chunk.get("section", ""),
                text_excerpt=chunk.get("text", "")[:200],
                confidence=chunk.get("confidence", 0.5),
            )
            sources.append(src)

    # Process tool results
    if tool_results:
        for result in tool_results:
            if isinstance(result, dict) and "error" not in result:
                answer_parts.append(json.dumps(result, ensure_ascii=False, indent=2))

    # Build final answer
    if answer_parts:
        answer = "\n\n".join(answer_parts)
    else:
        answer = "No encontré información relevante en los documentos procesados para responder esta pregunta."

    return ChatResponse(
        answer=answer,
        sources=sources,
        confidence=min(1.0, len(sources) * 0.2) if sources else 0.0,
    )


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def execute_tool(
    tool_name: str,
    arguments: dict,
    db_session=None,
) -> dict:
    """Execute a tool call and return results.

    In production, this would query the database and extraction services.
    """
    try:
        if tool_name == "get_plan_info":
            return _get_plan_info(arguments, db_session)
        elif tool_name == "get_plan_rooms":
            return _get_plan_rooms(arguments, db_session)
        elif tool_name == "get_room_dimensions":
            return _get_room_dimensions(arguments, db_session)
        elif tool_name == "get_plan_symbols":
            return _get_plan_symbols(arguments, db_session)
        elif tool_name == "get_technical_specs":
            return _get_technical_specs(arguments, db_session)
        elif tool_name == "find_material_by_room":
            return _find_material_by_room(arguments, db_session)
        elif tool_name == "get_work_items":
            return _get_work_items(arguments, db_session)
        elif tool_name == "aggregate_budget":
            return _aggregate_budget(arguments, db_session)
        elif tool_name == "compare_documents":
            return _compare_documents(arguments, db_session)
        elif tool_name == "search_technical_text":
            return _search_technical_text(arguments, db_session)
        else:
            return {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        logger.error(f"Tool execution error: {tool_name}: {e}")
        return {"error": str(e)}


def _get_plan_info(args: dict, db) -> dict:
    """Get plan information."""
    if not db:
        return {"error": "Database not available"}
    from sqlalchemy import select
    from app.models import Plan
    plan_id = args.get("plan_id")
    if not plan_id:
        return {"error": "plan_id required"}
    plan = db.get(Plan, plan_id)
    if not plan:
        return {"error": "Plan not found"}
    return {
        "project_name": plan.project_name,
        "scale": plan.scale_text,
        "phase": plan.project_phase,
        "revision": plan.revision,
        "has_valid_scale": plan.has_valid_scale,
    }


def _get_plan_rooms(args: dict, db) -> dict:
    """Get rooms from a plan."""
    if not db:
        return {"rooms": []}
    from sqlalchemy import select
    from app.models import PlanRoom
    plan_id = args.get("plan_id")
    if not plan_id:
        return {"error": "plan_id required"}
    rooms = list(db.scalars(select(PlanRoom).where(PlanRoom.plan_id == plan_id)).all())
    return {
        "rooms": [
            {"name": r.name, "area_m2": r.area_m2, "source": r.source}
            for r in rooms
        ]
    }


def _get_room_dimensions(args: dict, db) -> dict:
    """Get dimensions for a specific room."""
    if not db:
        return {"error": "Database not available"}
    from sqlalchemy import select
    from app.models import PlanRoom
    plan_id = args.get("plan_id")
    room_name = args.get("room_name", "")
    if not plan_id or not room_name:
        return {"error": "plan_id and room_name required"}
    rooms = list(db.scalars(
        select(PlanRoom).where(PlanRoom.plan_id == plan_id)
    ).all())
    for room in rooms:
        if room_name.lower() in (room.name or "").lower():
            return {
                "name": room.name,
                "area_m2": room.area_m2,
                "width_m": room.width_m,
                "length_m": room.length_m,
                "source": room.source,
                "confidence": room.confidence,
            }
    return {"error": f"Room '{room_name}' not found"}


def _get_plan_symbols(args: dict, db) -> dict:
    """Get symbol counts from a plan."""
    if not db:
        return {"symbols": {}}
    from sqlalchemy import select, func
    from app.models import PlanSymbol
    plan_id = args.get("plan_id")
    if not plan_id:
        return {"error": "plan_id required"}
    stmt = (
        select(PlanSymbol.symbol_class, func.count())
        .where(PlanSymbol.plan_id == plan_id)
        .group_by(PlanSymbol.symbol_class)
    )
    rows = list(db.scalars(stmt).all())
    return {"symbols": {r[0]: r[1] for r in rows}}


def _get_technical_specs(args: dict, db) -> dict:
    """Get technical specifications."""
    # Would query from extracted specs stored in DB
    return {"specs": []}


def _find_material_by_room(args: dict, db) -> dict:
    """Find materials used in a room."""
    room_name = args.get("room_name", "")
    element_type = args.get("element_type", "")
    # Would cross-reference memory specs with plan rooms
    return {"room": room_name, "element": element_type, "materials": []}


def _get_work_items(args: dict, db) -> dict:
    """Get work items from budget."""
    if not db:
        return {"items": []}
    from sqlalchemy import select
    from app.models import ConstructionWorkItem
    doc_id = args.get("document_id")
    if not doc_id:
        return {"error": "document_id required"}
    items = list(db.scalars(
        select(ConstructionWorkItem).where(ConstructionWorkItem.document_id == doc_id)
    ).all())
    return {
        "items": [
            {"code": i.code, "description": i.description, "unit": i.unit,
             "quantity": i.quantity, "total_price": float(i.total_price) if i.total_price else None}
            for i in items
        ]
    }


def _aggregate_budget(args: dict, db) -> dict:
    """Aggregate budget items."""
    return {"aggregation": {}}


def _compare_documents(args: dict, db) -> dict:
    """Compare plan and memory data."""
    return {"contradictions": []}


def _search_technical_text(args: dict, db) -> dict:
    """Search technical text."""
    query = args.get("query", "")
    return {"results": [], "query": query}
