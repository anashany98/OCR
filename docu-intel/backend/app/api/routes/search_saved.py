from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import get_db
from app.models import SavedSearch, User
from app.schemas.professional import SavedSearchCreate, SavedSearchRead

router = APIRouter()


@router.get("/saved", response_model=list[SavedSearchRead])
def list_saved_searches(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[SavedSearch]:
    return list(db.scalars(select(SavedSearch).where(SavedSearch.user_id == user.id).order_by(SavedSearch.created_at.desc())).all())


@router.post("/saved", response_model=SavedSearchRead)
def create_saved_search(payload: SavedSearchCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> SavedSearch:
    saved = SavedSearch(user_id=user.id, **payload.model_dump())
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved
