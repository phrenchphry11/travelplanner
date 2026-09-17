"""Real JWT verification, with a local RSA key standing in for Clerk's JWKS."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth
from app.config import Settings
from app.db import get_session
from app.main import app

ISSUER = "https://example-app.clerk.accounts.dev"
WEB = "https://travelplanner-web.onrender.com"


@pytest.fixture
def signer(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class FakeJWKS:
        def get_signing_key_from_jwt(self, _token):
            return type("Key", (), {"key": key.public_key()})()

    monkeypatch.setattr(auth, "_jwks_client", lambda: FakeJWKS())
    monkeypatch.setattr(
        auth, "get_settings",
        lambda: Settings(clerk_issuer=ISSUER, cors_origins=f"{WEB},http://localhost:5173"),
    )

    def sign(**overrides) -> str:
        now = int(time.time())
        claims = {"iss": ISSUER, "sub": "user_123", "iat": now, "exp": now + 60, "azp": WEB}
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, key, algorithm="RS256")

    return sign


def test_accepts_token_from_our_frontend(signer):
    assert auth.decode_clerk_token(signer())["sub"] == "user_123"
    assert auth.decode_clerk_token(signer(azp="http://localhost:5173"))["sub"] == "user_123"
    assert auth.decode_clerk_token(signer(azp=WEB + "/"))["sub"] == "user_123"


def test_rejects_token_issued_to_another_site(signer):
    with pytest.raises(HTTPException) as exc:
        auth.decode_clerk_token(signer(azp="https://evil.example.com"))
    assert exc.value.status_code == 401
    assert "authorized party" in exc.value.detail


def test_token_without_azp_follows_clerk_rule(signer):
    assert auth.decode_clerk_token(signer(azp=None))["sub"] == "user_123"


@pytest.mark.parametrize("overrides", [
    {"iss": "https://other-app.clerk.accounts.dev"},
    {"exp": int(time.time()) - 120},
    {"sub": None},
])
def test_rejects_wrong_issuer_expired_or_missing_subject(signer, overrides):
    with pytest.raises(HTTPException) as exc:
        auth.decode_clerk_token(signer(**overrides))
    assert exc.value.status_code == 401


def test_rejects_token_signed_by_another_key(signer):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    forged = jwt.encode({"iss": ISSUER, "sub": "x", "iat": now, "exp": now + 60, "azp": WEB}, other, algorithm="RS256")
    with pytest.raises(HTTPException) as exc:
        auth.decode_clerk_token(forged)
    assert exc.value.status_code == 401


def test_endpoint_rejects_foreign_azp_end_to_end(signer, engine):
    from sqlmodel import Session

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    try:
        client = TestClient(app)
        ok = client.get("/me", headers={"Authorization": f"Bearer {signer()}"})
        assert ok.status_code == 200 and ok.json()["id"] == "user_123"
        bad = client.get("/me", headers={"Authorization": f"Bearer {signer(azp='https://evil.example.com')}"})
        assert bad.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_authorized_parties_setting_overrides_cors_origins():
    s = Settings(cors_origins="https://a.example", authorized_parties="https://b.example/, https://c.example")
    assert s.authorized_party_list == ["https://b.example", "https://c.example"]
    assert Settings(cors_origins="https://a.example").authorized_party_list == ["https://a.example"]


def test_signing_in_stores_email_lowercase_and_redeems_a_case_mismatched_invite(signer, engine):
    """Regression: a Clerk email of different case than a pending invite used to leave
    the invite stranded forever, since redemption only runs at sign-in time."""
    from sqlmodel import Session, select

    from app.models import Trip, TripInvite, TripMember, User

    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    try:
        with Session(engine) as s:
            owner = User(id="owner", email="owner@example.com")
            s.add(owner)
            s.flush()
            trip = Trip(owner_id="owner", title="Portugal")
            s.add(trip)
            s.flush()
            s.add(TripMember(trip_id=trip.id, user_id="owner", role="owner"))
            s.add(TripInvite(trip_id=trip.id, email="person@example.com", invited_by="owner"))
            s.commit()
            trip_id = trip.id

        client = TestClient(app)
        res = client.get("/me", headers={"Authorization": f"Bearer {signer(sub='user_mixed', email='Person@Example.COM')}"})
        assert res.status_code == 200
        assert res.json()["email"] == "person@example.com"  # stored lowercase, not as Clerk sent it

        with Session(engine) as s:
            assert s.get(TripMember, (trip_id, "user_mixed")) is not None
            invite = s.exec(select(TripInvite).where(TripInvite.trip_id == trip_id)).one()
            assert invite.accepted_at is not None
    finally:
        app.dependency_overrides.clear()
