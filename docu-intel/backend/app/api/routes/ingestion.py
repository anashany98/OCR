from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_roles
from app.database.session import get_db
from app.ingestion.scanner import scan_input_folders
from app.models import User

router = APIRouter()


@router.post("/scan")
def scan(db: Session = Depends(get_db), user: User = Depends(require_roles("admin", "gestor"))) -> dict:
    return scan_input_folders(db, user=user, enqueue=True)

