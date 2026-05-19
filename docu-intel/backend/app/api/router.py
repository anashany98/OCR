from fastapi import APIRouter

from app.api.routes import (
    admin,
    ai,
    auth,
    budgets,
    document_workflow,
    documents,
    ingestion,
    invoices,
    integrations,
    jobs,
    orders,
    plans,
    plans_professional,
    professional_admin,
    reconciliation,
    search,
    search_saved,
    thumbnails,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(document_workflow.router, prefix="/documents", tags=["documents"])
api_router.include_router(thumbnails.router, prefix="/documents", tags=["thumbnails"])
api_router.include_router(ingestion.router, prefix="/ingestion", tags=["ingestion"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(search_saved.router, prefix="/search", tags=["search"])
api_router.include_router(budgets.router, prefix="/budgets", tags=["budgets"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(invoices.router, prefix="/invoices", tags=["invoices"])
api_router.include_router(plans.router, prefix="/plans", tags=["plans"])
api_router.include_router(plans_professional.router, prefix="/plans", tags=["plans"])
api_router.include_router(plans.rooms_router, prefix="/plan-rooms", tags=["plans"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(professional_admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(reconciliation.router, prefix="/reconciliation", tags=["reconciliation"])
api_router.include_router(integrations.router, prefix="/integrations/v1", tags=["integrations"])
