from sqlmodel import Session, select

from app.agents.research import CandidateIn, ResearchResult, ResearchUsage
from app.geocoding import GeoResult, locate_option
from app.models import Activity, Candidate, Lodging, Place
from worker.__main__ import claim_job, run_job

CITIES = ["Lisbon", "Lisbon", "Lisbon", "Porto", "Porto"]


def _confirm(client, cities=CITIES):
    body = {
        "title": "Portugal", "start_date": "2027-05-01", "destinations": ["Portugal"],
        "days": [{"base_city": c, "title": f"Day in {c}"} for c in cities],
    }
    return client.post("/intake/confirm", json=body).json()["id"]


def _option(name, **overrides):
    data = {
        "name": name, "summary": f"{name} summary", "pros": ["p"], "cons": ["c"], "confidence": "high",
        "price_range": "€150 per night", "address": "Rua A 1, Lisbon", "neighborhood": "Baixa",
        "lat": 38.71, "lng": -9.14, "website_url": f"https://{name.lower().replace(' ', '')}.example",
        "booking_url": None, "activity_kind": None, "best_time": None,
        "sources": [{"url": "https://s.example", "title": "S", "note": ""}],
    }
    data.update(overrides)
    return CandidateIn.model_validate(data)


def _research(client, engine, trip_id, kind, options, day_index=0, fetch=lambda p: []):
    board = client.get(f"/trips/{trip_id}/board").json()
    gaps = [g for g in board["gaps"] if g["kind"] == kind]
    gap = gaps[day_index] if kind == "activity" else gaps[0]
    client.post(f"/gaps/{gap['id']}/research")
    with Session(engine) as s:
        run_job(s, claim_job(s), runner=lambda ctx: ResearchResult(options, ResearchUsage()), fetch=fetch)
    board = client.get(f"/trips/{trip_id}/board").json()
    return board, next(g for g in board["gaps"] if g["id"] == gap["id"])


def test_choose_lodging_creates_stay_for_exact_nights(make_client, engine, session):
    client = make_client()
    trip_id = _confirm(client)
    board, gap = _research(client, engine, trip_id, "lodging", [_option("Hotel A"), _option("Hotel B")])
    a = gap["candidates"][0]

    res = client.post(f"/candidates/{a['id']}/choose")
    assert res.status_code == 200
    out = res.json()
    assert (out["gap_status"], out["candidate_status"], out["resolved_by_kind"]) == ("answered", "accepted", "lodging")

    stay = session.get(Lodging, out["resolved_by_id"])
    assert (stay.check_in.isoformat(), stay.check_out.isoformat()) == ("2027-05-01", "2027-05-04")  # 3 Lisbon nights
    assert stay.status == "planned"
    assert stay.notes == "€150 per night"
    assert stay.booking_url == "https://hotela.example"
    assert session.get(Place, stay.place_id).name == "Hotel A"

    board = client.get(f"/trips/{trip_id}/board").json()
    gap = next(g for g in board["gaps"] if g["id"] == gap["id"])
    assert gap["status"] == "answered" and gap["resolved_by_id"] == stay.id
    assert [c["name"] for c in gap["candidates"]] == ["Hotel B"]  # others stay available for a later change
    assert board["lodgings"][0]["notes"] == "€150 per night"
    assert board["trip"]["open_gap_count"] == 6  # 7 gaps before, one filled


def test_choose_activity_adds_to_day_in_order(make_client, engine, session):
    client = make_client()
    trip_id = _confirm(client)
    _, gap = _research(client, engine, trip_id, "activity", [
        _option("Tasca", activity_kind="meal", best_time="evening", booking_url="https://book.example"),
    ])
    out = client.post(f"/candidates/{gap['candidates'][0]['id']}/choose").json()
    act = session.get(Activity, out["resolved_by_id"])
    assert (act.name, act.kind, act.start_time, act.booking_url, act.status) == (
        "Tasca", "meal", "evening", "https://book.example", "planned",
    )
    assert act.day_id == gap["day_id"] and act.sort_order == 0


def test_cannot_choose_twice_or_choose_hidden(make_client, engine):
    client = make_client()
    trip_id = _confirm(client)
    _, gap = _research(client, engine, trip_id, "lodging", [_option("Hotel A"), _option("Hotel B"), _option("Hotel C")])
    a, b, c = (x["id"] for x in gap["candidates"])
    assert client.post(f"/candidates/{c}/reject").status_code == 200
    assert client.post(f"/candidates/{c}/choose").status_code == 409
    assert client.post(f"/candidates/{a}/choose").status_code == 200
    assert client.post(f"/candidates/{b}/choose").status_code == 409


def test_reject_with_reason_restore_and_board_hidden_list(make_client, engine, session):
    client = make_client()
    trip_id = _confirm(client)
    _, gap = _research(client, engine, trip_id, "lodging", [_option("Hotel A"), _option("Hotel B")])
    b = gap["candidates"][1]["id"]

    assert client.post(f"/candidates/{b}/reject", json={"reason": "  too far out  "}).json()["candidate_status"] == "rejected"
    assert session.get(Candidate, b).rejection_reason == "too far out"
    board = client.get(f"/trips/{trip_id}/board").json()
    g = next(x for x in board["gaps"] if x["id"] == gap["id"])
    assert [c["name"] for c in g["candidates"]] == ["Hotel A"]
    assert g["hidden"] == [{"id": b, "name": "Hotel B", "reason": "too far out"}]

    assert client.post(f"/candidates/{b}/reject").status_code == 409
    assert client.post(f"/candidates/{b}/restore").json()["candidate_status"] == "proposed"
    assert client.post(f"/candidates/{b}/restore").status_code == 409
    assert client.post(f"/candidates/{b}/reject", json={"reason": "x" * 301}).status_code == 422


def test_reopen_removes_plan_item_and_restores_options(make_client, engine, session):
    client = make_client()
    trip_id = _confirm(client)
    _, gap = _research(client, engine, trip_id, "lodging", [_option("Hotel A"), _option("Hotel B")])
    a, b = (x["id"] for x in gap["candidates"])
    stay_id = client.post(f"/candidates/{a}/choose").json()["resolved_by_id"]

    out = client.post(f"/gaps/{gap['id']}/reopen").json()
    assert (out["gap_status"], out["candidate_id"], out["candidate_status"]) == ("open", a, "proposed")
    session.expire_all()
    assert session.get(Lodging, stay_id) is None
    board = client.get(f"/trips/{trip_id}/board").json()
    g = next(x for x in board["gaps"] if x["id"] == gap["id"])
    assert g["status"] == "open" and g["resolved_by_id"] is None
    assert sorted(c["name"] for c in g["candidates"]) == ["Hotel A", "Hotel B"]
    assert board["lodgings"] == []

    assert client.post(f"/gaps/{gap['id']}/reopen").status_code == 409
    assert client.post(f"/candidates/{b}/choose").status_code == 200


def test_choices_are_private(make_client, engine):
    owner = make_client("owner")
    trip_id = _confirm(owner)
    _, gap = _research(owner, engine, trip_id, "lodging", [_option("Hotel A")])
    cid = gap["candidates"][0]["id"]
    stranger = make_client("stranger")
    for path in (f"/candidates/{cid}/choose", f"/candidates/{cid}/reject", f"/candidates/{cid}/restore", f"/gaps/{gap['id']}/reopen"):
        assert stranger.post(path).status_code == 404
    assert owner.post("/candidates/nope/choose").status_code == 404


def test_worker_pins_options_near_the_base_city(make_client, engine, session):
    client = make_client()
    trip_id = _confirm(client)
    # Pretend the Lisbon city pin exists.
    lisbon = session.exec(select(Place).where(Place.trip_id == trip_id, Place.name == "Lisbon")).one()
    lisbon.lat, lisbon.lng = 38.72, -9.14
    session.add(lisbon)
    session.commit()

    answers = {
        "Portugal": [GeoResult(39.6, -8.0, "Portugal", "boundary", "pt")],
        "Rua Near 1, Lisbon": [GeoResult(38.71, -9.13, "Rua Near", "building", "pt")],
        "Rua Far 9, Lisbon": [GeoResult(41.15, -8.61, "Rua Far in Porto", "building", "pt")],
        "Far Hotel, Lisbon": [],
    }
    fetch = lambda params: answers.get(params["q"], [])  # noqa: E731
    board, gap = _research(client, engine, trip_id, "lodging", [
        _option("Near Hotel", lat=None, lng=None, address="Rua Near 1, Lisbon"),
        _option("Far Hotel", lat=None, lng=None, address="Rua Far 9, Lisbon"),
    ], fetch=fetch)

    places = {p["name"]: p for p in board["places"]}
    assert (places["Near Hotel"]["lat"], places["Near Hotel"]["precision"]) == (38.71, "approximate")
    assert places["Far Hotel"]["lat"] is None  # 270 km away: no pin rather than a wrong one
    assert places["Near Hotel"]["address"] == "Rua Near 1, Lisbon"


def test_locate_option_requires_a_reference(session):
    calls = []
    assert locate_option(session, "X", "Addr", "City", [], None, lambda p: calls.append(p) or []) is None
    assert calls == []


def test_locate_option_without_base_requires_trip_country(session):
    fetch = lambda p: [GeoResult(48.85, 2.35, "Paris place", "amenity", "fr")]  # noqa: E731
    assert locate_option(session, "Café", None, "Paris", ["gb"], None, fetch) is None
    assert locate_option(session, "Café 2", None, "Paris", ["fr"], None, fetch).lat == 48.85


def test_locate_option_skips_roads(session):
    fetch = lambda p: [GeoResult(38.7, -9.1, "Some road", "highway", "pt")]  # noqa: E731
    assert locate_option(session, "Hotel", "Road 1", "Lisbon", ["pt"], (38.72, -9.14), fetch) is None
