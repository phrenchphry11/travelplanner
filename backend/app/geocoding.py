"""City geocoding via OpenStreetMap Nominatim.

Usage policy: https://operations.osmfoundation.org/policies/nominatim/
- at most one request per second (process-wide lock below)
- identifying User-Agent (settings.nominatim_user_agent)
- results cached (GeocodeCache table), never re-queried
- server-side only; never used for autocomplete or bulk lookups

Lookups are structured, never free-text "City, Destination" strings: those
matched shops and streets (e.g. "Paris, Edinburgh" -> a shop called Victor
Paris in Edinburgh). A city is looked up as a settlement, limited to the trip's
countries when known, and only boundary/place results are ever accepted.
"""
from __future__ import annotations

import json
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
# Administrative areas and named places. Excludes shops, buildings, roads, hotels.
ACCEPTED_CATEGORIES = {"boundary", "place"}


@dataclass
class GeoResult:
    lat: float
    lng: float
    display_name: str
    category: str = ""
    country_code: str = ""


# Takes Nominatim search params (q, featureType, countrycodes, limit); returns results in rank order.
Fetcher = Callable[[dict], list[GeoResult]]


def nominatim_search(params: dict) -> list[GeoResult]:
    """One rate-limited Nominatim search."""
    global _last_request
    settings = get_settings()
    with _lock:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            res = httpx.get(
                f"{settings.nominatim_url.rstrip('/')}/search",
                params={"format": "jsonv2", "addressdetails": 1, "limit": 1, **params},
                headers={"User-Agent": settings.nominatim_user_agent},
                timeout=10,
            )
        finally:
            _last_request = time.monotonic()
    res.raise_for_status()
    return [
        GeoResult(
            lat=float(row["lat"]),
            lng=float(row["lon"]),
            display_name=row.get("display_name", ""),
            category=row.get("category", ""),
            country_code=(row.get("address") or {}).get("country_code", ""),
        )
        for row in res.json()
    ]


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _cache_key(params: dict) -> str:
    normalized = {k: (_normalize(v) if isinstance(v, str) else v) for k, v in params.items()}
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False)


def cached_lookup(session: Session, params: dict, fetch: Fetcher) -> GeoResult | None:
    """First accepted result for these params, from cache or one network call.

    Only the accepted result (or the fact that none was acceptable) is cached.
    Network errors propagate and are not cached.
    """
    key = _cache_key(params)
    hit = session.get(GeocodeCache, key)
    if hit is not None:
        if not hit.found:
            return None
        return GeoResult(hit.lat, hit.lng, hit.display_name, hit.category, hit.country_code)
    result = next((r for r in fetch(params) if r.category in ACCEPTED_CATEGORIES), None)
    session.add(GeocodeCache(
        query=key,
        found=result is not None,
        lat=result.lat if result else None,
        lng=result.lng if result else None,
        display_name=result.display_name if result else "",
        category=result.category if result else "",
        country_code=result.country_code if result else "",
    ))
    session.commit()
    return result


def country_codes_for(session: Session, destinations: list[str], fetch: Fetcher) -> list[str]:
    """ISO country codes for a trip's destinations ('Scotland' -> gb, 'Portugal' -> pt)."""
    codes: list[str] = []
    for dest in destinations:
        result = cached_lookup(session, {"q": dest}, fetch)
        if result and result.country_code and result.country_code not in codes:
            codes.append(result.country_code)
    return codes


def locate_city(session: Session, city: str, country_codes: list[str], fetch: Fetcher) -> GeoResult | None:
    attempts: list[dict] = []
    if country_codes:
        attempts.append({"q": city, "featureType": "settlement", "countrycodes": ",".join(sorted(country_codes))})
    attempts.append({"q": city, "featureType": "settlement"})
    if country_codes:
        # Regions and districts (not towns) inside the trip's countries.
        attempts.append({"q": city, "countrycodes": ",".join(sorted(country_codes)), "limit": 5})
    for params in attempts:
        result = cached_lookup(session, params, fetch)
        if result:
            return result
    return None


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
    fetch: Fetcher = nominatim_search,
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
        if not any(needs_lookup(p) for p in places):
            return
        try:
            codes = country_codes_for(session, list(trip.destinations or []), fetch)
        except (httpx.HTTPError, ValueError, KeyError):
            session.rollback()
            log.warning("country lookup failed for trip %s; locating without country limits", trip_id, exc_info=True)
            codes = []

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
                result = locate_city(session, place.name, codes, fetch)
            except (httpx.HTTPError, ValueError, KeyError):
                # Leave geocoded_at set: needs_lookup() retries after RETRY_AFTER.
                session.rollback()
                log.warning("geocoding %r failed; will retry later", place.name, exc_info=True)
                continue
            if result:
                place.lat, place.lng, place.precision = result.lat, result.lng, "approximate"
                session.add(place)
                session.commit()
            else:
                log.info("no settlement or area found for %r (countries %s)", place.name, codes)


def get_trip_locator() -> Callable[[str], None]:
    """FastAPI dependency so tests can replace network geocoding."""
    return geocode_trip_places
