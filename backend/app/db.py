from collections.abc import Generator

from sqlalchemy import create_engine
from sqlmodel import Session

from app.config import get_settings


def _make_engine():
    url = get_settings().database_url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


engine = _make_engine()


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
