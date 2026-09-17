import os

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app.auth import current_user
from app.db import get_session
from app.geocoding import get_trip_locator
from app.main import app
from app.models import User


@pytest.fixture(autouse=True)
def no_real_anthropic_calls(monkeypatch):
    """Tests must never spend money. Any code path that reaches a real
    Anthropic client fails immediately; tests inject fakes instead."""
    from app.agents import intake, research

    def _blocked():
        raise RuntimeError("Tests must not call the real Anthropic API; inject a fake runner or client.")

    monkeypatch.setattr(intake, "_client", _blocked)
    monkeypatch.setattr(research, "_client", _blocked)


@pytest.fixture(autouse=True)
def no_real_nominatim_calls(monkeypatch):
    """Tests must not hit OpenStreetMap either; pass a fake fetch instead."""
    from app import geocoding

    def _blocked():
        raise RuntimeError("Tests must not call Nominatim; pass a fake fetch.")

    monkeypatch.setattr(geocoding, "default_fetcher", _blocked)


@pytest.fixture
def engine():
    """In-memory SQLite by default. Set TEST_DATABASE_URL to run against Postgres,
    which enforces foreign keys the way production does."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        engine = create_engine(url)
        SQLModel.metadata.drop_all(engine)
        SQLModel.metadata.create_all(engine)
        yield engine
        engine.dispose()
        return
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Enforce foreign keys like Postgres does.
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    SQLModel.metadata.create_all(engine)
    yield engine


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
        from app.collaborators import redeem_invites

        user_id = request.headers["x-test-user"]
        with Session(engine) as s:
            user = s.get(User, user_id)
            if user is None:
                # Mirrors app.auth.current_user: a brand-new user gets any invites
                # waiting for their email redeemed right away.
                user = User(id=user_id, email=f"{user_id}@example.com")
                s.add(user)
                s.commit()
                s.refresh(user)
                redeem_invites(s, user)
                s.refresh(user)  # redeem_invites may have committed again, which expires attributes
            return user

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[current_user] = _user
    # Never hit Nominatim from tests unless a test installs its own locator.
    app.dependency_overrides[get_trip_locator] = lambda: (lambda trip_id: None)

    def _make(user_id: str = "user_a") -> TestClient:
        return TestClient(app, headers={"x-test-user": user_id})

    yield _make
    app.dependency_overrides.clear()
