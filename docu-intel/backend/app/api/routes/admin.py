from fastapi import APIRouter

from app.api.routes import (
    admin_access,
    admin_dashboard,
    admin_integrations,
    admin_jobs,
    admin_learning,
    admin_operations,
    admin_quality,
    admin_system,
)

router = APIRouter()
router.include_router(admin_system.router)
router.include_router(admin_operations.router)
router.include_router(admin_jobs.router)
router.include_router(admin_quality.router)
router.include_router(admin_integrations.router)
router.include_router(admin_access.router)
router.include_router(admin_learning.router)
router.include_router(admin_dashboard.router)
