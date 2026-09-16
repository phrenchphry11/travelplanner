from datetime import datetime, timedelta, timezone

import httpx
from sqlmodel import Session, select

from app.geocoding import (
    GeoResult,
    cached_lookup,
    country_codes_for,
    geocode_trip_places,
    locate_city,
    needs_lookup,
)
from app.models import GeocodeCache, Place, Trip, User, utcnow


def _trip_with_cities(session, cities, destinations=("Portugal",)):
    session.add(User(id="u", email="u@example.com"))
    session.flush()
    trip = Trip(owner_id="u", title="t", destinations=list(destinations))
    session.add(trip)
    session.flush()
    places = [Place(trip_id=trip.id, name=c, kind="city") for c in cities]
    session.add_all(places)
    session.commit()
    return trip, places


def _key(params):
    return (params["q"], params.get("featureType"), params.get("countrycodes"))


class FakeNominatim:
    """Answers keyed by (q, featureType, countrycodes); records every call."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, params):
        self.calls.append(_key(params))
        answer = self.answers.get(_key(params), [])
        if isinstance(answer, Exception):
            raise answer
        return answer


def city(lat, lng, name, cc):
    return GeoResult(lat, lng, name, category="boundary", country_code=cc)


PORTUGAL = GeoResult(39.6, -8.0, "Portugal", category="boundary", country_code="pt")


def test_locates_cities_as_settlements_within_trip_countries(engine, session):
    trip, _ = _trip_with_cities(session, ["Lisbon", "Porto"])
    fake = FakeNominatim({
        ("Portugal", None, None): [PORTUGAL],
        ("Lisbon", "settlement", "pt"): [city(38.72, -9.14, "Lisboa", "pt")],
        ("Porto", "settlement", "pt"): [city(41.15, -8.61, "Porto", "pt")],
    })
    geocode_trip_places(trip.id, session_factory=lambda: Session(engine), fetch=fake)
    with Session(engine) as s:
        found = {p.name: (p.lat, p.lng, p.precision) for p in s.exec(select(Place))}
    assert found == {"Lisbon": (38.72, -9.14, "approximate"), "Porto": (41.15, -8.61, "approximate")}
    assert fake.calls == [("Portugal", None, None), ("Lisbon", "settlement", "pt"), ("Porto", "settlement", "pt")]


def test_edinburgh_trip_puts_paris_in_france(engine, session):
    """Regression: 'Paris, Edinburgh' used to match a shop called Victor Paris in Edinburgh."""
    trip, _ = _trip_with_cities(session, ["Edinburgh", "London", "Paris"], destinations=["Edinburgh", "France"])
    fake = FakeNominatim({
        ("Edinburgh", None, None): [city(55.95, -3.19, "Edinburgh", "gb")],
        ("France", None, None): [GeoResult(46.6, 1.9, "France", category="boundary", country_code="fr")],
        ("Edinburgh", "settlement", "fr,gb"): [city(55.95, -3.19, "Edinburgh", "gb")],
        ("London", "settlement", "fr,gb"): [city(51.51, -0.13, "London", "gb")],
        ("Paris", "settlement", "fr,gb"): [city(48.85, 2.35, "Paris", "fr")],
    })
    geocode_trip_places(trip.id, session_factory=lambda: Session(engine), fetch=fake)
    with Session(engine) as s:
        paris = s.exec(select(Place).where(Place.name == "Paris")).one()
    assert (paris.lat, paris.lng) == (48.85, 2.35)
    assert not any("," in q for q, _, _ in fake.calls), "never query free-text 'City, Destination'"


def test_settlement_outside_trip_countries_still_found(session):
    fake = FakeNominatim({("Geneva", "settlement", None): [city(46.2, 6.14, "Genève", "ch")]})
    assert locate_city(session, "Geneva", ["fr"], fake).lat == 46.2
    assert fake.calls == [("Geneva", "settlement", "fr"), ("Geneva", "settlement", None)]


def test_region_found_as_administrative_area_within_countries(session):
    fake = FakeNominatim({
        ("Alentejo", None, "pt"): [
            GeoResult(38.5, -7.9, "UTAD building", category="building", country_code="pt"),
            GeoResult(38.2, -7.8, "Alentejo", category="boundary", country_code="pt"),
        ],
    })
    assert locate_city(session, "Alentejo", ["pt"], fake).display_name == "Alentejo"


def test_never_accepts_shops_buildings_or_roads(session):
    junk = [
        GeoResult(41.29, -7.74, "UTAD Douro Valley Center", category="building", country_code="pt"),
        GeoResult(41.20, -7.70, "Quinta winery", category="tourism", country_code="pt"),
        GeoResult(41.0, -7.0, "Douro Valley Road", category="highway", country_code="pt"),
    ]
    fake = FakeNominatim({("Douro Valley", None, "pt"): junk})
    assert locate_city(session, "Douro Valley", ["pt"], fake) is None


def test_region_search_is_only_tried_with_country_limits(session):
    fake = FakeNominatim({})
    assert locate_city(session, "Somewhere", [], fake) is None
    assert fake.calls == [("Somewhere", "settlement", None)]


def test_country_codes_are_deduplicated_and_skip_unknowns(session):
    fake = FakeNominatim({
        ("Scotland", None, None): [GeoResult(56.8, -4.1, "Scotland", category="boundary", country_code="gb")],
        ("England", None, None): [GeoResult(52.5, -1.5, "England", category="boundary", country_code="gb")],
        ("France", None, None): [GeoResult(46.6, 1.9, "France", category="boundary", country_code="fr")],
    })
    assert country_codes_for(session, ["Scotland", "England", "Nowhere", "France"], fake) == ["gb", "fr"]


def test_cache_prevents_repeat_network_calls_and_caches_misses(session):
    fake = FakeNominatim({("Lisbon", "settlement", None): [city(1.0, 2.0, "x", "pt")]})
    params = {"q": "Lisbon", "featureType": "settlement"}
    assert cached_lookup(session, params, fake).lat == 1.0
    assert cached_lookup(session, {"q": "  lisbon ", "featureType": "settlement"}, fake).country_code == "pt"
    assert cached_lookup(session, {"q": "Atlantis", "featureType": "settlement"}, fake) is None
    assert cached_lookup(session, {"q": "Atlantis", "featureType": "settlement"}, fake) is None
    assert fake.calls == [("Lisbon", "settlement", None), ("Atlantis", "settlement", None)]
    assert len(session.exec(select(GeocodeCache)).all()) == 2


def test_skips_places_already_attempted(engine, session):
    trip, places = _trip_with_cities(session, ["Lisbon"])
    places[0].geocoded_at = utcnow()
    session.add(places[0])
    session.commit()
    fake = FakeNominatim({})
    geocode_trip_places(trip.id, session_factory=lambda: Session(engine), fetch=fake)
    assert fake.calls == []


def test_network_error_is_not_cached_and_waits_before_retry(engine, session):
    trip, _ = _trip_with_cities(session, ["Lisbon"], destinations=())
    fake = FakeNominatim({("Lisbon", "settlement", None): httpx.ConnectError("down")})
    geocode_trip_places(trip.id, session_factory=lambda: Session(engine), fetch=fake)
    with Session(engine) as s:
        place = s.exec(select(Place)).one()
        assert place.lat is None and place.geocoded_at is not None
        assert s.exec(select(GeocodeCache)).all() == []
        assert not needs_lookup(place)
        assert needs_lookup(place, now=datetime.now(timezone.utc) + timedelta(minutes=16))


def test_country_lookup_failure_still_locates_without_limits(engine, session):
    trip, _ = _trip_with_cities(session, ["Lisbon"], destinations=["Portugal"])
    fake = FakeNominatim({
        ("Portugal", None, None): httpx.ConnectError("down"),
        ("Lisbon", "settlement", None): [city(38.72, -9.14, "Lisboa", "pt")],
    })
    geocode_trip_places(trip.id, session_factory=lambda: Session(engine), fetch=fake)
    with Session(engine) as s:
        assert s.exec(select(Place)).one().lat == 38.72


def test_needs_lookup_ignores_non_cities_and_located_places():
    assert not needs_lookup(Place(trip_id="t", name="Cafe", kind="coffee"))
    assert not needs_lookup(Place(trip_id="t", name="Lisbon", kind="city", lat=1.0, lng=2.0))
    assert needs_lookup(Place(trip_id="t", name="Lisbon", kind="city"))
