"""City geocoding via OpenStreetMap Nominatim.

Usage policy: https://operations.osmfoundation.org/policies/nominatim/
- at most one request per second (process-wide lock below)
- identifying User-Agent (settings.nominatim_user_agent)
- results cached (GeocodeCache table), never re-queried
- server-side only; never used for autocomplete or bulk lookups
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import update
from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine
from app.models import GeocodeCache, Place, Trip, utcnow

log = logging.getLogger(__name__)

_lock = threading.Lock()
_last_request = 0.0
MIN_INTERVAL_SECONDS = 1.1
RETRY_AFTER = timedelta(minutes=15)


@dataclass
class GeoResult:
    lat: float
    lng: float
    display_name: str


Fetcher = Callable[[str], GeoResult | None]


def nominatim_fetch(query: str) -> GeoResult | None:
    """One rate-limited Nominatim search. Returns None when nothing matches."""
    global _last_request
    settings = get_settings()
    with _lock:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            res = httpx.get(
                f"{settings.nominatim_url.rstrip('/')}/search",
                params={"q": query, "format": "jsonv2", "limit": 1},
                headers={"User-Agent": settings.nominatim_user_agent},
                timeout=10,
            )
        finally:
            _last_request = time.monotonic()
    res.raise_for_status()
    rows = res.json()
    if not rows:
        return None
    row = rows[0]
    return GeoResult(lat=float(row["lat"]), lng=float(row["lon"]), display_name=row.get("display_name", ""))


def _normalize(query: str) -> str:
    return " ".join(query.casefold().split())


def cached_geocode(session: Session, query: str, fetch: Fetcher) -> GeoResult | None:
    key = _normalize(query)
    hit = session.get(GeocodeCache, key)
    if hit is not None:
        return GeoResult(hit.lat, hit.lng, hit.display_name) if hit.found else None
    result = fetch(query)  # network errors propagate and are NOT cached
    session.add(GeocodeCache(
        query=key,
        found=result is not None,
        lat=result.lat if result else None,
        lng=result.lng if result else None,
        display_name=result.display_name if result else "",
    ))
    session.commit()
    return result


def _queries_for(city: str, destinations: list[str]) -> list[str]:
    """Try the city with the trip's first destination for context, then alone."""
    queries = []
    context = next((d for d in destinations if _normalize(d) != _normalize(city)), None)
    if context:
        queries.append(f"{city}, {context}")
    queries.append(city)
    return queries


def _as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; everything we store is UTC.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def needs_lookup(place: Place, now: datetime | None = None) -> bool:
    """Never tried, or tried without a result long enough ago to retry.

    Not-found answers are cached, so a retry only reaches the network when the
    earlier attempt failed with a network or server error.
    """
    if place.kind != "city" or place.lat is not None:
        return False
    if place.geocoded_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    return now - _as_utc(place.geocoded_at) >= RETRY_AFTER


def geocode_trip_places(
    trip_id: str,
    session_factory: Callable[[], Session] = lambda: Session(engine),
    fetch: Fetcher = nominatim_fetch,
) -> None:
    """Locate a trip's city places that need it.

    Safe to call repeatedly and concurrently: each place is claimed with a
    compare-and-set on geocoded_at before any network call.
    """
    with session_factory() as session:
        trip = session.get(Trip, trip_id)
        if trip is None:
            return
        places = session.exec(select(Place).where(Place.trip_id == trip_id, Place.kind == "city")).all()
        for place in places:
            if not needs_lookup(place):
                continue
            previous = place.geocoded_at
            claim = update(Place).where(Place.id == place.id).values(geocoded_at=utcnow())
            claim = claim.where(Place.geocoded_at.is_(None) if previous is None else Place.geocoded_at == previous)
            claimed = session.exec(claim)
            session.commit()
            if claimed.rowcount != 1:
                continue
            session.refresh(place)
            try:
                result = None
                for query in _queries_for(place.name, trip.destinations or []):
                    result = cached_geocode(session, query, fetch)
                    if result:
                        break
            except (httpx.HTTPError, ValueError, KeyError):
                # Leave geocoded_at set: needs_lookup() retries after RETRY_AFTER.
                session.rollback()
                log.warning("geocoding %r failed; will retry later", place.name, exc_info=True)
                continue
            if result:
                place.lat, place.lng, place.precision = result.lat, result.lng, "approximate"
                session.add(place)
                session.commit()


def get_trip_locator() -> Callable[[str], None]:
    """FastAPI dependency so tests can replace network geocoding."""
    return geocode_trip_places
