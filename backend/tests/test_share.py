import json
from datetime import date

from fastapi.testclient import TestClient

from app.auth import current_user
from app.main import app
from app.models import (
    Activity,
    Candidate,
    Day,
    Gap,
    Lodging,
    Place,
    ResearchJob,
    Source,
    Trip,
    TripMember,
)
from app.routers import share


def _create_trip(client) -> str:
    res = client.post("/trips", json={"title": "Portugal", "start_date": "2027-05-01", "end_date": "2027-05-03"})
    assert res.status_code == 201
    return res.json()["id"]


def _public_client() -> TestClient:
    """A client with no auth header and no auth override: any use of current_user fails."""
    app.dependency_overrides.pop(current_user, None)
    return TestClient(app)


def _fill_trip(session, trip_id: str) -> None:
    """A trip carrying every kind of private data the public link must not show."""
    lisbon = Place(trip_id=trip_id, name="Lisbon", kind="city", lat=38.72, lng=-9.14, notes="PRIVATE place note")
    porto = Place(trip_id=trip_id, name="Porto", kind="city")  # not pinned
    hotel = Place(
        trip_id=trip_id, name="Casa do Rio", kind="lodging", lat=38.71, lng=-9.13,
        address="Rua do Rio 1, Lisbon", website_url="https://casa.example", summary="PRIVATE place summary",
    )
    cafe = Place(trip_id=trip_id, name="Pastéis Café", kind="food", address="Belém")
    session.add_all([lisbon, porto, hotel, cafe])
    session.flush()
    d1 = Day(trip_id=trip_id, date=date(2027, 5, 1), title="Arrive", summary="Settle in", notes="PRIVATE day note", base_place_id=lisbon.id)
    d2 = Day(trip_id=trip_id, date=date(2027, 5, 2), title="Belém", base_place_id=lisbon.id)
    d3 = Day(trip_id=trip_id, date=date(2027, 5, 3), title="Train north", base_place_id=porto.id)
    session.add_all([d1, d2, d3])
    session.flush()
    session.add(Lodging(
        trip_id=trip_id, place_id=hotel.id, check_in=date(2027, 5, 1), check_out=date(2027, 5, 3),
        booking_url="https://book.example/casa", confirmation_code="CONF-SECRET-123",
        cost=987.65, currency="EUR", status="booked", notes="€140–€180 per night",
    ))
    session.add_all([
        Activity(trip_id=trip_id, day_id=d2.id, name="Fado night", time_of_day="evening", sort_order=0, notes="Live music"),
        Activity(trip_id=trip_id, day_id=d2.id, name="Custard tarts", place_id=cafe.id, time_of_day="morning", sort_order=1,
                 booking_url="https://tarts.example"),
        Activity(trip_id=trip_id, day_id=d2.id, name="Wander", time_of_day="", sort_order=2),
        Activity(trip_id=trip_id, day_id=d2.id, name="Tower visit", time_of_day="afternoon", sort_order=3),
    ])
    gap = Gap(trip_id=trip_id, day_id=d3.id, kind="lodging", prompt="GAP-PROMPT Where to stay in Porto")
    session.add(gap)
    session.flush()
    proposed = Candidate(trip_id=trip_id, gap_id=gap.id, target_kind="lodging", status="proposed",
                         payload={"name": "PROPOSED-HOTEL", "price_range": "€999"}, summary="CANDIDATE-SUMMARY")
    rejected = Candidate(trip_id=trip_id, gap_id=gap.id, target_kind="lodging", status="rejected",
                         payload={"name": "REJECTED-HOTEL"}, rejection_reason="REJECTION-REASON")
    session.add_all([proposed, rejected])
    session.flush()
    session.add(Source(trip_id=trip_id, subject_kind="candidate", subject_id=proposed.id, url="https://source.example/secret"))
    session.add(ResearchJob(trip_id=trip_id, gap_id=gap.id, nudge="RESEARCH-NUDGE", error="JOB-ERROR"))
    session.commit()


def test_publish_unpublish_regenerate_lifecycle(make_client):
    owner = make_client("owner")
    trip_id = _create_trip(owner)
    assert owner.get(f"/trips/{trip_id}").json()["share_slug"] is None
    assert owner.get(f"/trips/{trip_id}/board").json()["trip"]["share_slug"] is None

    slug = owner.post(f"/trips/{trip_id}/share").json()["share_slug"]
    assert slug and len(slug) >= 22
    assert owner.post(f"/trips/{trip_id}/share").json()["share_slug"] == slug  # idempotent
    assert owner.get(f"/trips/{trip_id}/board").json()["trip"]["share_slug"] == slug
    assert owner.get(f"/share/{slug}").status_code == 200

    new_slug = owner.post(f"/trips/{trip_id}/share/regenerate").json()["share_slug"]
    assert new_slug and new_slug != slug
    assert owner.get(f"/share/{slug}").status_code == 404
    assert owner.get(f"/share/{new_slug}").status_code == 200

    assert owner.delete(f"/trips/{trip_id}/share").json() == {"share_slug": None}
    assert owner.get(f"/share/{new_slug}").status_code == 404
    assert owner.get(f"/trips/{trip_id}").json()["share_slug"] is None

    again = owner.post(f"/trips/{trip_id}/share").json()["share_slug"]
    assert again not in (slug, new_slug)


def test_strangers_cannot_manage_sharing(make_client, session):
    owner = make_client("owner")
    trip_id = _create_trip(owner)
    stranger = make_client("stranger")
    assert stranger.post(f"/trips/{trip_id}/share").status_code == 404
    assert stranger.post(f"/trips/{trip_id}/share/regenerate").status_code == 404
    assert stranger.delete(f"/trips/{trip_id}/share").status_code == 404
    assert session.get(Trip, trip_id).share_slug is None

    # A non-owner member (none exist in v1) is refused too.
    make_client("editor").get("/trips")  # creates the user row
    session.add(TripMember(trip_id=trip_id, user_id="editor", role="editor"))
    session.commit()
    assert make_client("editor").post(f"/trips/{trip_id}/share").status_code == 403


def test_public_payload_is_stripped(make_client, session):
    owner = make_client("owner")
    trip_id = _create_trip(owner)
    _fill_trip(session, trip_id)
    slug = owner.post(f"/trips/{trip_id}/share").json()["share_slug"]

    res = _public_client().get(f"/share/{slug}")
    assert res.status_code == 200
    body = res.json()
    raw = json.dumps(body, ensure_ascii=False)

    forbidden = [
        trip_id, "owner", "@example.com", "CONF-SECRET-123", "987.65", "EUR", "€", "PRIVATE",
        "GAP-PROMPT", "PROPOSED-HOTEL", "REJECTED-HOTEL", "REJECTION-REASON", "CANDIDATE-SUMMARY",
        "source.example", "RESEARCH-NUDGE", "JOB-ERROR", slug,
    ]
    for value in forbidden:
        assert value not in raw, value
    forbidden_keys = {"id", "trip_id", "day_id", "place_id", "owner_id", "user_id", "email", "confirmation_code",
                      "cost", "currency", "price_range", "status", "gaps", "candidates", "sources", "jobs", "share_slug"}

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    assert not forbidden_keys & set(keys(body))

    assert set(body) == {"title", "start_date", "end_date", "days", "stays"}
    assert body["title"] == "Portugal"
    assert [d["date"] for d in body["days"]] == ["2027-05-01", "2027-05-02", "2027-05-03"]
    first = body["days"][0]
    assert first == {"date": "2027-05-01", "title": "Arrive", "summary": "Settle in",
                     "city": {"name": "Lisbon", "address": "", "lat": 38.72, "lng": -9.14}, "plans": []}
    assert body["days"][2]["city"] == {"name": "Porto", "address": "", "lat": None, "lng": None}

    plans = body["days"][1]["plans"]
    assert [p["name"] for p in plans] == ["Custard tarts", "Tower visit", "Fado night", "Wander"]
    assert plans[0] == {
        "name": "Custard tarts", "time": "morning",
        "place": {"name": "Pastéis Café", "address": "Belém", "lat": None, "lng": None},
        "booking_url": "https://tarts.example", "website_url": "", "notes": "",
    }
    assert body["stays"] == [{
        "place": {"name": "Casa do Rio", "address": "Rua do Rio 1, Lisbon", "lat": 38.71, "lng": -9.13},
        "check_in": "2027-05-01", "check_out": "2027-05-03", "nights": 2,
        "booking_url": "https://book.example/casa", "website_url": "https://casa.example",
    }]


def test_public_route_has_no_auth_dependency():
    route = next(r for r in share.router.routes if r.path == "/share/{slug}")

    def calls(dependant):
        for d in dependant.dependencies:
            yield d.call
            yield from calls(d)

    assert current_user not in set(calls(route.dependant))


def test_noindex_headers_and_unknown_slug(make_client):
    owner = make_client("owner")
    trip_id = _create_trip(owner)
    slug = owner.post(f"/trips/{trip_id}/share").json()["share_slug"]
    public = _public_client()

    ok = public.get(f"/share/{slug}")
    assert ok.status_code == 200
    assert ok.headers["x-robots-tag"] == "noindex, nofollow"
    assert ok.headers["cache-control"] == "no-store"

    for bad in ("nope", trip_id, "x" * 200):
        missing = public.get(f"/share/{bad}")
        assert missing.status_code == 404
        assert missing.headers["x-robots-tag"] == "noindex, nofollow"
        assert "Portugal" not in missing.text
