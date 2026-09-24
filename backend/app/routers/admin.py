"""Internal admin view. Every route is admin-only and 404s for anyone else."""
from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.auth import require_admin
from app.costs import cost_summary
from app.db import get_session

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/costs")
def costs(session: Session = Depends(get_session)) -> dict:
    return cost_summary(session)
