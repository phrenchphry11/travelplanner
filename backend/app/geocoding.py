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
import math
import re
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
from app.models import Activity, Candidate, Day, Gap, GeocodeCache, Lodging, Place, Trip, utcnow

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


def default_fetcher() -> Fetcher:
    """Looked up at call time (not bound as a default argument) so tests can block the network."""
    return nominatim_search


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _cache_key(params: dict) -> str:
    normalized = {k: (_normalize(v) if isinstance(v, str) else v) for k, v in params.items()}
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False)


def is_area(result: GeoResult) -> bool:
    return result.category in ACCEPTED_CATEGORIES


def is_located_poi(result: GeoResult) -> bool:
    # Hotels, restaurants, buildings, and addresses are all fine for an option;
    # a bare road isn't a place anyone can go to.
    return result.category != "highway"


def cached_lookup(
    session: Session,
    params: dict,
    fetch: Fetcher,
    accept: Callable[[GeoResult], bool] = is_area,
) -> GeoResult | None:
    """First accepted result for these params, from cache or one network call.

    Only the accepted result (or the fact that none was acceptable) is cached,
    keyed by params plus the acceptance rule. Network errors propagate and are
    not cached.
    """
    key = _cache_key({**params, "_accept": accept.__name__})
    hit = session.get(GeocodeCache, key)
    if hit is not None:
        if not hit.found:
            return None
        return GeoResult(hit.lat, hit.lng, hit.display_name, hit.category, hit.country_code)
    result = next((r for r in fetch(params) if accept(r)), None)
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


MAX_TRIP_SPREAD_KM = 1500.0


def locate_city(
    session: Session,
    city: str,
    country_codes: list[str],
    fetch: Fetcher,
    nearby: list[tuple[float, float]] | None = None,
) -> GeoResult | None:
    """Pin a trip's base place.

    Tries a town/city in the trip's countries, then an administrative area in
    those countries, then a town/city anywhere. The last step must still be
    near the trip: in one of its countries, or within MAX_TRIP_SPREAD_KM of the
    trip's other pinned cities. Otherwise vague names like "Central France"
    match far-away places (it matched Ville de France in Goiânia, Brazil).
    """
    nearby = nearby or []
    limits = ",".join(sorted(country_codes))
    if country_codes:
        result = cached_lookup(session, {"q": city, "featureType": "settlement", "countrycodes": limits}, fetch)
        if result:
            return result
        # Regions and districts (not towns) inside the trip's countries.
        result = cached_lookup(session, {"q": city, "countrycodes": limits, "limit": 5}, fetch)
        if result:
            return result
    result = cached_lookup(session, {"q": city, "featureType": "settlement"}, fetch)
    if result is None:
        return None
    if country_codes and result.country_code in country_codes:
        return result
    if nearby and min(distance_km(n, (result.lat, result.lng)) for n in nearby) <= MAX_TRIP_SPREAD_KM:
        return result
    if not country_codes and not nearby:
        return result  # nothing to compare against
    log.info("ignoring %r for %r: not near the trip", result.display_name, city)
    return None


MAX_OPTION_DISTANCE_KM = 40.0


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


_NAME_BREAKS = re.compile(r"\s*(?:\(|–|—|,|:|\bcity cent(?:re|er)\b|\bloop\b|\bday trip\b|\bwalk\b|\btour\b)", re.IGNORECASE)


def leading_place(name: str) -> str:
    """'Clermont-Ferrand city centre (Place de Jaude area)' -> 'Clermont-Ferrand'."""
    return _NAME_BREAKS.split(name, maxsplit=1)[0].strip()


def locate_option(
    session: Session,
    name: str,
    address: str | None,
    city: str | None,
    country_codes: list[str],
    near: tuple[float, float] | None,
    fetch: Fetcher,
    map_query: str | None = None,
) -> GeoResult | None:
    """Find a research option (a hotel, restaurant, sight, area) on the map.

    Tries, in order: its address, the searchable `map_query` research gave, its
    name with the day's city, then the town at the start of its name as a
    settlement (a city-level pin for descriptive names like "Blois–Chambord
    loop"). Every result must be within MAX_OPTION_DISTANCE_KM of the day's
    base city, or, with no base pin, in one of the trip's countries.
    """
    if near is None and not country_codes:
        return None  # nothing to sanity-check against; better no pin than a wrong one
    limits = {"countrycodes": ",".join(sorted(country_codes))} if country_codes else {}

    def with_city(q: str) -> str:
        return q if (not city or city.casefold() in q.casefold()) else f"{q}, {city}"

    attempts: list[tuple[dict, Callable[[GeoResult], bool]]] = []
    if address:
        attempts.append(({"q": with_city(address), **limits}, is_located_poi))
    if map_query:
        attempts.append(({"q": map_query, **limits}, is_located_poi))
    attempts.append(({"q": with_city(name), **limits}, is_located_poi))
    town = leading_place(name)
    if town and town.casefold() != name.casefold():
        attempts.append(({"q": town, "featureType": "settlement", **limits}, is_area))

    for params, accept in attempts:
        result = cached_lookup(session, params, fetch, accept=accept)
        if result is None:
            continue
        if near is not None and distance_km(near, (result.lat, result.lng)) > MAX_OPTION_DISTANCE_KM:
            log.info("ignoring %r for %r: %.0f km from base", result.display_name, name, distance_km(near, (result.lat, result.lng)))
            continue
        if near is None and result.country_code not in country_codes:
            continue
        return result
    return None


def _as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; everything we store is UTC.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def needs_lookup(place: Place, now: datetime | None = None) -> bool:
    """Unpinned, and never tried or tried long enough ago to retry. Applies to
    city places and to option/chosen places (hotels, restaurants).

    Not-found answers are cached, so a retry only reaches the network when the
    earlier attempt failed with a network or server error.
    """
    if place.lat is not None:
        return False
    if place.geocoded_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    return now - _as_utc(place.geocoded_at) >= RETRY_AFTER


def _claim(session: Session, place: Place) -> bool:
    """Compare-and-set geocoded_at so concurrent lookups never duplicate work."""
    previous = place.geocoded_at
    claim = update(Place).where(Place.id == place.id).values(geocoded_at=utcnow())
    claim = claim.where(Place.geocoded_at.is_(None) if previous is None else Place.geocoded_at == previous)
    claimed = session.exec(claim)
    session.commit()
    if claimed.rowcount != 1:
        return False
    session.refresh(place)
    return True


def _trip_country_codes(session: Session, trip: Trip, fetch: Fetcher) -> list[str]:
    try:
        return country_codes_for(session, list(trip.destinations or []), fetch)
    except (httpx.HTTPError, ValueError, KeyError):
        session.rollback()
        log.warning("country lookup failed for trip %s; locating without country limits", trip.id, exc_info=True)
        return []


def geocode_trip_places(
    trip_id: str,
    session_factory: Callable[[], Session] = lambda: Session(engine),
    fetch: Fetcher | None = None,
) -> None:
    """Pin a trip's base cities, in trip order, then its unpinned options.

    Safe to call repeatedly and concurrently: each place is claimed with a
    compare-and-set on geocoded_at before any network call.
    """
    fetch = fetch or default_fetcher()
    with session_factory() as session:
        trip = session.get(Trip, trip_id)
        if trip is None:
            return
        cities = session.exec(select(Place).where(Place.trip_id == trip_id, Place.kind == "city")).all()
        options = session.exec(select(Place).where(Place.trip_id == trip_id, Place.kind != "city")).all()
        if not any(needs_lookup(p) for p in (*cities, *options)):
            return
        codes = _trip_country_codes(session, trip, fetch)

        order = {d.base_place_id: i for i, d in reversed(list(enumerate(
            session.exec(select(Day).where(Day.trip_id == trip_id).order_by(Day.date)).all()
        )))}
        cities = sorted(cities, key=lambda p: order.get(p.id, len(order)))
        nearby = [(p.lat, p.lng) for p in cities if p.lat is not None and p.lng is not None]

        for place in cities:
            if not needs_lookup(place) or not _claim(session, place):
                continue
            try:
                result = locate_city(session, place.name, codes, fetch, nearby)
            except (httpx.HTTPError, ValueError, KeyError):
                # Leave geocoded_at set: needs_lookup() retries after RETRY_AFTER.
                session.rollback()
                log.warning("geocoding %r failed; will retry later", place.name, exc_info=True)
                continue
            if result:
                place.lat, place.lng, place.precision = result.lat, result.lng, "approximate"
                session.add(place)
                session.commit()
                nearby.append((result.lat, result.lng))
            else:
                log.info("no nearby settlement or area found for %r (countries %s)", place.name, codes)

        _locate_options(session, trip_id, [p for p in options if needs_lookup(p)], codes, fetch)


def _locate_options(session: Session, trip_id: str, places: list[Place], codes: list[str], fetch: Fetcher) -> None:
    """Best-effort pins for option, chosen, and manually-entered places near their day's base city."""
    if not places:
        return
    place_ids = [p.id for p in places]
    by_place = {c.place_id: c for c in session.exec(
        select(Candidate).where(Candidate.trip_id == trip_id, Candidate.place_id.in_(place_ids))
    )}
    # Plans the traveler added themselves have a place but no research option.
    activity_by_place = {a.place_id: a for a in session.exec(
        select(Activity).where(Activity.trip_id == trip_id, Activity.place_id.in_(place_ids))
    )}
    # Same for a manually-entered stay: a Lodging with a place but no Candidate.
    lodging_by_place = {l.place_id: l for l in session.exec(
        select(Lodging).where(Lodging.trip_id == trip_id, Lodging.place_id.in_(place_ids))
    )}
    for place in places:
        candidate = by_place.get(place.id)
        activity = activity_by_place.get(place.id)
        lodging = lodging_by_place.get(place.id)
        if candidate is None and activity is None and lodging is None and not place.saved:
            continue
        if not _claim(session, place):
            continue
        if candidate is not None:
            gap = session.get(Gap, candidate.gap_id)
            day_id = gap.day_id if gap else None
        elif activity is not None:
            day_id = activity.day_id
        elif lodging is not None:
            # A stay's own day_id isn't stored; its first night is the day it started.
            first_night = session.exec(
                select(Day).where(Day.trip_id == trip_id, Day.date == lodging.check_in)
            ).first()
            day_id = first_night.id if first_night else None
        else:
            day_id = None  # a saved place isn't tied to any day; just check it's in the trip's countries
        day = session.get(Day, day_id) if day_id else None
        base = session.get(Place, day.base_place_id) if day and day.base_place_id else None
        near = (base.lat, base.lng) if base and base.lat is not None and base.lng is not None else None
        payload = (candidate.payload or {}) if candidate is not None else {}
        try:
            result = locate_option(
                session, payload.get("name") or place.name, payload.get("address") or place.address or None,
                base.name if base else None, codes, near, fetch, map_query=payload.get("map_query"),
            )
        except (httpx.HTTPError, ValueError, KeyError):
            session.rollback()
            log.warning("locating option %r failed; will retry later", place.name, exc_info=True)
            continue
        if result:
            place.lat, place.lng, place.precision = result.lat, result.lng, "approximate"
            session.add(place)
            session.commit()


def get_trip_locator() -> Callable[[str], None]:
    """FastAPI dependency so tests can replace network geocoding."""
    return geocode_trip_places
