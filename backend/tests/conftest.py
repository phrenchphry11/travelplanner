import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.auth import current_user
from app.db import get_session
from app.geocoding import get_trip_locator
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
    """Build a TestClient authenticated as the given user id.

    Each client sends its user in a test-only header, so several clients for
    different users can be used side by side in one test.
    """

    def _session():
        with Session(engine) as s:
            yield s

    def _user(request: Request):
        user_id = request.headers["x-test-user"]
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
    # Never hit Nominatim from tests unless a test installs its own locator.
    app.dependency_overrides[get_trip_locator] = lambda: (lambda trip_id: None)

    def _make(user_id: str = "user_a") -> TestClient:
        return TestClient(app, headers={"x-test-user": user_id})

    yield _make
    app.dependency_overrides.clear()
