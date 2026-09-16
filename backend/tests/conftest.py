import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.auth import current_user
from app.db import get_session
from app.main import app
from app.models import User


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def make_client(engine):
    """Build a TestClient authenticated as the given user id."""
    clients = []

    def _make(user_id: str = "user_a") -> TestClient:
        def _session():
            with Session(engine) as s:
                yield s

        def _user():
            with Session(engine) as s:
                user = s.get(User, user_id)
                if user is None:
                    user = User(id=user_id, email=f"{user_id}@example.com")
                    s.add(user)
                    s.commit()
                    s.refresh(user)
                return user

        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[current_user] = _user
        client = TestClient(app)
        clients.append(client)
        return client

    yield _make
    app.dependency_overrides.clear()
