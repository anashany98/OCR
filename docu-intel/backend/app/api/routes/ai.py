from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agent import answer_question
from app.api.deps import get_current_user
from app.database.session import get_db
from app.models import AIAnswer, AIQuestion, User
from app.schemas.ai import AIAnswerRead, AIQuestionRead, AskRequest

router = APIRouter()


@router.post("/ask", response_model=AIAnswerRead)
async def ask(
    payload: AskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AIAnswer:
    return await answer_question(db, user=user, question=payload.question, mode=payload.mode)


@router.get("/history", response_model=list[AIQuestionRead])
def history(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[AIQuestion]:
    return list(db.scalars(select(AIQuestion).where(AIQuestion.user_id == user.id).order_by(AIQuestion.id.desc()).limit(50)).all())


@router.get("/answers/{answer_id}", response_model=AIAnswerRead)
def answer(answer_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> AIAnswer:
    item = db.get(AIAnswer, answer_id)
    if not item:
        raise HTTPException(status_code=404, detail="Answer not found")
    return item
