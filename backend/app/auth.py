"""Clerk JWT verification for FastAPI.

The frontend sends `Authorization: Bearer <session token>`. We verify the RS256
signature against Clerk's JWKS and upsert a local User row.
"""
from __future__ import annotations

import ssl
from functools import lru_cache

import certifi

import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient
from sqlmodel import Session

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
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer or None,
            options={"verify_aud": False},
            leeway=10,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc


def current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    claims = decode_clerk_token(_bearer_token(request))
    user_id = claims["sub"]
    user = session.get(User, user_id)
    email = claims.get("email") or ""
    display_name = claims.get("name") or claims.get("first_name") or ""
    if user is None:
        user = User(id=user_id, email=email, display_name=display_name)
        session.add(user)
        session.commit()
        session.refresh(user)
    elif (email and user.email != email) or (display_name and user.display_name != display_name):
        user.email = email or user.email
        user.display_name = display_name or user.display_name
        session.add(user)
        session.commit()
    return user
