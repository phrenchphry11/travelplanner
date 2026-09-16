from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlmodel import Session

from app.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/health/db")
def health_db(session: Session = Depends(get_session)) -> dict:
    session.exec(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
