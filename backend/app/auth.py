"""Clerk JWT verification for FastAPI.

The frontend sends `Authorization: Bearer <session token>`. We verify the RS256
signature, expiry, and issuer against Clerk's JWKS, check the token was issued
to one of our own frontends (azp), and upsert a local User row.
"""
from __future__ import annotations

import ssl
from functools import lru_cache

import certifi
import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient
from sqlmodel import Session

from app.collaborators import redeem_invites
from app.config import get_settings
from app.db import get_session
from app.models import User


@lru_cache
def _jwks_client() -> PyJWKClient:
    # Use certifi's CA bundle: python.org macOS builds ship without system certs.
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    return PyJWKClient(get_settings().jwks_url, cache_keys=True, ssl_context=ssl_context)


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return token


def decode_clerk_token(token: str) -> dict:
    settings = get_settings()
    if not settings.clerk_issuer and not settings.clerk_jwks_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth not configured")
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer or None,
            options={"verify_aud": False, "require": ["exp", "iat", "sub"]},
            leeway=10,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc
    check_authorized_party(claims, settings.authorized_party_list)
    return claims


def check_authorized_party(claims: dict, allowed: list[str]) -> None:
    """Reject tokens issued to a frontend we don't own.

    Matches Clerk's own authorizedParties rule: when a token carries azp, it
    must be one of ours. Clerk browser session tokens always include azp.
    """
    azp = claims.get("azp")
    if azp is not None and azp.rstrip("/") not in allowed:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token: unexpected authorized party")


def current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    claims = decode_clerk_token(_bearer_token(request))
    user_id = claims["sub"]
    user = session.get(User, user_id)
    email = (claims.get("email") or "").strip().lower()  # normalized so it always matches an invite
    display_name = claims.get("name") or claims.get("first_name") or ""
    if user is None:
        user = User(id=user_id, email=email, display_name=display_name)
        session.add(user)
        session.commit()
        session.refresh(user)
        redeem_invites(session, user)
    elif (email and user.email != email) or (display_name and user.display_name != display_name):
        email_changed = bool(email and user.email != email)
        user.email = email or user.email
        user.display_name = display_name or user.display_name
        session.add(user)
        session.commit()
        if email_changed:
            redeem_invites(session, user)
    return user


def is_admin(user: User) -> bool:
    return bool(user.email) and user.email in get_settings().admin_email_list


def require_admin(user: User = Depends(current_user)) -> User:
    """404 rather than 403 for everyone else, so the admin view isn't advertised."""
    if not is_admin(user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return user
