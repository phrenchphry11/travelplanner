from datetime import datetime, timedelta, timezone

import httpx
from sqlmodel import Session, select

from app.geocoding import GeoResult, cached_geocode, geocode_trip_places, needs_lookup
from app.models import GeocodeCache, Place, Trip, User


def _trip_with_cities(session, cities, destinations=("Portugal",)):
    session.add(User(id="u", email="u@example.com"))
    trip = Trip(owner_id="u", title="t", destinations=list(destinations))
    session.add(trip)
    places = [Place(trip_id=trip.id, name=c, kind="city") for c in cities]
    session.add_all(places)
    session.commit()
    return trip, places


class FakeFetch:
    def __init__(self, answers):
        self.answers = answers
        self.queries = []

    def __call__(self, query):
        self.queries.append(query)
        answer = self.answers.get(query)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_locates_cities_with_destination_context(engine, session):
    trip, _ = _trip_with_cities(session, ["Lisbon", "Porto"])
    fetch = FakeFetch({
        "Lisbon, Portugal": GeoResult(38.72, -9.14, "Lisboa"),
        "Porto, Portugal": GeoResult(41.15, -8.61, "Porto"),
    })
    geocode_trip_places(trip.id, session_factory=lambda: Session(engine), fetch=fetch)
    with Session(engine) as s:
        found = {p.name: (p.lat, p.lng, p.precision) for p in s.exec(select(Place))}
    assert found == {"Lisbon": (38.72, -9.14, "approximate"), "Porto": (41.15, -8.61, "approximate")}
    assert fetch.queries == ["Lisbon, Portugal", "Porto, Portugal"]


def test_falls_back_to_city_alone_and_caches_misses(engine, session):
    trip, _ = _trip_with_cities(session, ["Sintra"])
    fetch = FakeFetch({"Sintra": GeoResult(38.8, -9.39, "Sintra")})
    geocode_trip_places(trip.id, session_factory=lambda: Session(engine), fetch=fetch)
    assert fetch.queries == ["Sintra, Portugal", "Sintra"]
    with Session(engine) as s:
        misses = s.exec(select(GeocodeCache).where(GeocodeCache.found == False)).all()  # noqa: E712
        assert [m.query for m in misses] == ["sintra, portugal"]


def test_cache_prevents_repeat_network_calls(session):
    fetch = FakeFetch({"Lisbon": GeoResult(1.0, 2.0, "x")})
    assert cached_geocode(session, "Lisbon", fetch).lat == 1.0
    assert cached_geocode(session, "  lisbon ", fetch).lat == 1.0
    assert fetch.queries == ["Lisbon"]


def test_skips_places_already_attempted(engine, session):
    trip, places = _trip_with_cities(session, ["Lisbon"])
    places[0].geocoded_at = datetime.now(timezone.utc)
    session.add(places[0])
    session.commit()
    fetch = FakeFetch({})
    geocode_trip_places(trip.id, session_factory=lambda: Session(engine), fetch=fetch)
    assert fetch.queries == []


def test_network_error_is_not_cached_and_waits_before_retry(engine, session):
    trip, _ = _trip_with_cities(session, ["Lisbon"], destinations=())
    fetch = FakeFetch({"Lisbon": httpx.ConnectError("down")})
    geocode_trip_places(trip.id, session_factory=lambda: Session(engine), fetch=fetch)
    with Session(engine) as s:
        place = s.exec(select(Place)).one()
        assert place.lat is None and place.geocoded_at is not None
        assert s.exec(select(GeocodeCache)).all() == []
        assert not needs_lookup(place)
        assert needs_lookup(place, now=datetime.now(timezone.utc) + timedelta(minutes=16))


def test_needs_lookup_ignores_non_cities_and_located_places():
    assert not needs_lookup(Place(trip_id="t", name="Cafe", kind="coffee"))
    assert not needs_lookup(Place(trip_id="t", name="Lisbon", kind="city", lat=1.0, lng=2.0))
    assert needs_lookup(Place(trip_id="t", name="Lisbon", kind="city"))
