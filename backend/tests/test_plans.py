from sqlmodel import Session, select

from app.agents.research import ResearchResult, ResearchUsage, _format_context
from app.geocoding import GeoResult, geocode_trip_places, get_trip_locator
from app.main import app
from app.models import Activity, Gap, Place, ResearchJob
from tests.test_choices import _confirm, _option, _research
from worker.__main__ import claim_job, run_job


def _board(client, trip_id):
    return client.get(f"/trips/{trip_id}/board").json()


def _add(client, day_id, name, **fields):
    res = client.post(f"/days/{day_id}/plans", json={"name": name, **fields})
    assert res.status_code == 201, res.text
    return res.json()


def _day_plans(board, day_id):
    return [(a["name"], a["time_of_day"]) for a in board["activities"] if a["day_id"] == day_id]


def _run_worker(engine, options):
    captured = {}

    def runner(ctx):
        captured["ctx"] = ctx
        return ResearchResult(options, ResearchUsage())

    with Session(engine) as s:
        run_job(s, claim_job(s), runner=runner, fetch=lambda p: [])
    return captured["ctx"]


def test_a_day_holds_many_plans_ordered_by_time_of_day(make_client, engine):
    client = make_client()
    trip_id = _confirm(client)
    day = _board(client, trip_id)["days"][0]["id"]

    _add(client, day, "Fado show", time_of_day="evening")
    _add(client, day, "Whenever: pastries")
    _add(client, day, "Castle", time_of_day="morning")
    _, gap = _research(client, engine, trip_id, "activity", [_option("Tile museum", activity_kind="sight", best_time="afternoon")])
    assert client.post(f"/candidates/{gap['candidates'][0]['id']}/choose").status_code == 200
    _add(client, day, "Coffee", time_of_day="morning")

    assert _day_plans(_board(client, trip_id), day) == [
        ("Castle", "morning"), ("Coffee", "morning"), ("Tile museum", "afternoon"),
        ("Fado show", "evening"), ("Whenever: pastries", ""),
    ]


def test_find_ideas_makes_a_request_researched_with_the_day_and_stay(make_client, engine, session):
    client = make_client()
    trip_id = _confirm(client)
    board = _board(client, trip_id)
    day = board["days"][1]["id"]

    # A chosen stay covering that night, and a plan already on the day.
    _, lodging_gap = _research(client, engine, trip_id, "lodging", [_option("Hotel A")])
    client.post(f"/candidates/{lodging_gap['candidates'][0]['id']}/choose")
    _add(client, day, "Tram 28", time_of_day="morning")
    count_before = _board(client, trip_id)["trip"]["open_gap_count"]

    res = client.post(f"/days/{day}/plan-requests", json={"request": "  dinner near  our hotel ", "time_of_day": "evening"})
    assert res.status_code == 202
    gap_id = res.json()["gap_id"]

    board = _board(client, trip_id)
    gap = next(g for g in board["gaps"] if g["id"] == gap_id)
    assert (gap["prompt"], gap["origin"], gap["time_of_day"], gap["status"], gap["day_id"]) == (
        "Dinner near our hotel", "request", "evening", "researching", day,
    )
    assert gap["job"]["status"] == "queued" and gap["missing"]
    assert board["trip"]["open_gap_count"] == count_before + 1

    ctx = _run_worker(engine, [
        _option("Tasca", activity_kind="meal", best_time="afternoon"),
        _option("Cervejaria", activity_kind="meal", best_time="evening"),
        _option("Taberna", activity_kind="meal", best_time="evening"),
    ])
    assert ctx.is_request and ctx.time_of_day == "evening"
    assert ctx.planned_that_day == ["Tram 28 (morning)"]
    assert ctx.stay == "Hotel A, Baixa, Rua A 1, Lisbon"
    text = _format_context(ctx)
    assert "in the traveler's words: Dinner near our hotel" in text
    assert "Time of day: evening" in text
    assert "Staying that night at: Hotel A, Baixa, Rua A 1, Lisbon" in text
    assert "- Tram 28 (morning)" in text

    # Every drawer action works on a request.
    gap = next(g for g in _board(client, trip_id)["gaps"] if g["id"] == gap_id)
    assert gap["status"] == "open" and len(gap["candidates"]) == 3
    tasca, cerv, taberna = (c["id"] for c in gap["candidates"])
    assert client.post(f"/candidates/{taberna}/reject", json={"reason": "too far"}).status_code == 200
    assert client.post(f"/candidates/{taberna}/restore").status_code == 200
    assert client.post(f"/gaps/{gap_id}/research", json={"nudge": "cheaper"}).status_code == 202
    session.exec(select(ResearchJob).where(ResearchJob.gap_id == gap_id, ResearchJob.status == "queued")).one()
    ctx = _run_worker(engine, [_option("Snack bar", activity_kind="meal")])
    assert ctx.nudge == "cheaper" and "Tasca" in ctx.already_suggested

    out = client.post(f"/candidates/{tasca}/choose").json()
    act = session.get(Activity, out["resolved_by_id"])
    assert act.time_of_day == "evening"  # the traveler's time wins over the option's best time
    assert client.post(f"/gaps/{gap_id}/reopen").status_code == 200
    assert client.post(f"/candidates/{cerv}/choose").status_code == 200


def test_find_ideas_validation(make_client):
    client = make_client()
    trip_id = _confirm(client)
    day = _board(client, trip_id)["days"][0]["id"]
    assert client.post(f"/days/{day}/plan-requests", json={"request": "   "}).status_code == 422
    assert client.post(f"/days/{day}/plan-requests", json={"request": "x", "time_of_day": "night"}).status_code == 422
    assert client.post("/days/nope/plan-requests", json={"request": "x"}).status_code == 404


def test_add_plan_yourself_pins_it_when_found_near_the_day(make_client, engine, session):
    client = make_client()
    trip_id = _confirm(client)
    lisbon = session.exec(select(Place).where(Place.trip_id == trip_id, Place.name == "Lisbon")).one()
    lisbon.lat, lisbon.lng = 38.72, -9.14
    session.add(lisbon)
    session.commit()

    answers = {
        "Portugal": [GeoResult(39.6, -8.0, "Portugal", "boundary", "pt")],
        "Rua Augusta 2, Lisbon": [GeoResult(38.71, -9.137, "Rua Augusta", "building", "pt")],
        "Livraria Lello, Lisbon": [GeoResult(41.147, -8.611, "Livraria Lello, Porto", "shop", "pt")],
    }
    calls = []

    def fetch(params):
        calls.append(params["q"])
        return answers.get(params["q"], [])

    app.dependency_overrides[get_trip_locator] = lambda: (
        lambda tid: geocode_trip_places(tid, session_factory=lambda: Session(engine), fetch=fetch)
    )
    day = _board(client, trip_id)["days"][0]["id"]
    near = _add(client, day, "Arch walk", address="Rua Augusta 2", time_of_day="morning", link="example.com/arch", notes="Go early")
    far = _add(client, day, "Livraria Lello")  # found, but 270 km away in Porto
    nothing = _add(client, day, "Picnic with Ana")  # not found at all

    board = _board(client, trip_id)
    places = {p["id"]: p for p in board["places"]}
    assert (places[near["place_id"]]["lat"], places[near["place_id"]]["address"]) == (38.71, "Rua Augusta 2")
    assert places[far["place_id"]]["lat"] is None
    assert places[nothing["place_id"]]["lat"] is None
    assert not any(p["locating"] for p in board["places"] if p["kind"] != "city")
    assert near["link"] == "https://example.com/arch" and near["notes"] == "Go early"
    assert _day_plans(board, day) == [("Arch walk", "morning"), ("Livraria Lello", ""), ("Picnic with Ana", "")]
    assert "Picnic with Ana, Lisbon" in calls


def test_add_plan_works_with_no_pin_and_validates(make_client):
    client = make_client()  # default test locator does nothing
    trip_id = _confirm(client)
    day = _board(client, trip_id)["days"][0]["id"]
    plan = _add(client, day, "Rest day")
    assert plan["time_of_day"] == "" and plan["link"] == ""
    assert client.post(f"/days/{day}/plans", json={"name": "  "}).status_code == 422
    assert client.post(f"/days/{day}/plans", json={"name": "x", "link": "not a link"}).status_code == 422
    assert client.post(f"/days/{day}/plans", json={"name": "x", "link": "javascript:alert(1)"}).status_code == 422


def test_edit_plan(make_client, session):
    client = make_client()
    trip_id = _confirm(client)
    day = _board(client, trip_id)["days"][0]["id"]
    plan = _add(client, day, "Musem", time_of_day="morning")
    _add(client, day, "Lunch", time_of_day="afternoon")

    res = client.patch(f"/activities/{plan['id']}", json={
        "name": "Museum", "time_of_day": "afternoon", "notes": " Closed Mondays ", "link": "http://museum.example",
    })
    assert res.status_code == 200
    out = res.json()
    assert (out["name"], out["time_of_day"], out["notes"], out["link"]) == (
        "Museum", "afternoon", "Closed Mondays", "http://museum.example",
    )
    assert session.get(Place, plan["place_id"]).name == "Museum"
    assert _day_plans(_board(client, trip_id), day) == [("Lunch", "afternoon"), ("Museum", "afternoon")]

    assert client.patch(f"/activities/{plan['id']}", json={"link": ""}).json()["link"] == ""
    assert client.patch(f"/activities/{plan['id']}", json={"name": ""}).status_code == 422
    assert client.patch(f"/activities/{plan['id']}", json={"link": "ftp://x"}).status_code == 422


def test_reorder_within_part_of_day(make_client):
    client = make_client()
    trip_id = _confirm(client)
    day = _board(client, trip_id)["days"][0]["id"]
    a = _add(client, day, "A", time_of_day="morning")
    b = _add(client, day, "B", time_of_day="morning")
    c = _add(client, day, "C", time_of_day="morning")
    d = _add(client, day, "D", time_of_day="evening")

    res = client.post(f"/activities/{c['id']}/move", json={"direction": "up"})
    assert res.status_code == 200
    assert [p["name"] for p in res.json()] == ["A", "C", "B", "D"]
    client.post(f"/activities/{a['id']}/move", json={"direction": "down"})
    assert [n for n, _ in _day_plans(_board(client, trip_id), day)] == ["C", "A", "B", "D"]

    assert client.post(f"/activities/{c['id']}/move", json={"direction": "up"}).status_code == 409  # already first
    assert client.post(f"/activities/{b['id']}/move", json={"direction": "down"}).status_code == 409  # evening is next
    assert client.post(f"/activities/{d['id']}/move", json={"direction": "sideways"}).status_code == 422


def test_remove_manual_plan_deletes_it_and_its_place(make_client, session):
    client = make_client()
    trip_id = _confirm(client)
    day = _board(client, trip_id)["days"][0]["id"]
    plan = _add(client, day, "Picnic", address="Park")
    res = client.delete(f"/activities/{plan['id']}")
    assert res.status_code == 200 and res.json() == {"removed": "deleted", "gap_id": None}
    session.expire_all()
    assert session.get(Activity, plan["id"]) is None
    assert session.get(Place, plan["place_id"]) is None
    assert client.delete(f"/activities/{plan['id']}").status_code == 404


def test_remove_chosen_plan_brings_options_back(make_client, engine, session):
    client = make_client()
    trip_id = _confirm(client)
    _, gap = _research(client, engine, trip_id, "activity", [_option("Castle"), _option("Museum")])
    chosen = gap["candidates"][0]
    activity_id = client.post(f"/candidates/{chosen['id']}/choose").json()["resolved_by_id"]

    res = client.delete(f"/activities/{activity_id}")
    assert res.json() == {"removed": "reopened", "gap_id": gap["id"]}
    board = _board(client, trip_id)
    g = next(x for x in board["gaps"] if x["id"] == gap["id"])
    assert g["status"] == "open" and sorted(c["name"] for c in g["candidates"]) == ["Castle", "Museum"]
    assert board["activities"] == []
    session.expire_all()
    assert session.get(Place, chosen["place_id"]) is not None  # the option keeps its place


def test_starter_gap_only_counts_while_the_day_is_empty(make_client, engine):
    client = make_client()
    trip_id = _confirm(client)  # 5 days: 2 stays + 5 starter plan gaps
    board = _board(client, trip_id)
    day0, day1 = board["days"][0]["id"], board["days"][1]["id"]
    starter0 = next(g for g in board["gaps"] if g["kind"] == "activity" and g["day_id"] == day0)

    def counts():
        b = _board(client, trip_id)
        days = {d["id"]: d["open_gap_count"] for d in client.get(f"/trips/{trip_id}/days").json()}
        listed = next(t for t in client.get("/trips").json() if t["id"] == trip_id)["open_gap_count"]
        assert b["trip"]["open_gap_count"] == listed == client.get(f"/trips/{trip_id}").json()["open_gap_count"]
        return b, listed, days

    b, total, days = counts()
    assert (total, days[day0], days[day1]) == (7, 2, 1)  # day0 also holds the Lisbon stay gap

    plan = _add(client, day0, "Castle")
    b, total, days = counts()
    assert (total, days[day0]) == (6, 1)
    g = next(x for x in b["gaps"] if x["id"] == starter0["id"])
    assert g["status"] == "open" and not g["missing"]  # still there, just not missing
    assert client.post(f"/gaps/{starter0['id']}/research").status_code == 202  # still usable from its button

    client.delete(f"/activities/{plan['id']}")
    b, total, days = counts()
    assert (total, days[day0]) == (7, 2)
    assert next(x for x in b["gaps"] if x["id"] == starter0["id"])["missing"]

    # A request counts until something is chosen from it or it's removed.
    req = client.post(f"/days/{day1}/plan-requests", json={"request": "Dinner"}).json()["gap_id"]
    _, total, days = counts()
    assert (total, days[day1]) == (8, 2)
    assert client.post(f"/gaps/{req}/dismiss").status_code == 204
    _, total, days = counts()
    assert (total, days[day1]) == (7, 1)
    assert client.post(f"/gaps/{req}/dismiss").status_code == 409
    assert client.post(f"/gaps/{starter0['id']}/dismiss").status_code == 409  # starters can't be removed


def test_plans_are_private(make_client, engine, session):
    owner = make_client("owner")
    trip_id = _confirm(owner)
    day = _board(owner, trip_id)["days"][0]["id"]
    plan = _add(owner, day, "Castle")
    req = owner.post(f"/days/{day}/plan-requests", json={"request": "Dinner"}).json()["gap_id"]

    stranger = make_client("stranger")
    assert stranger.post(f"/days/{day}/plans", json={"name": "Mine"}).status_code == 404
    assert stranger.post(f"/days/{day}/plan-requests", json={"request": "Mine"}).status_code == 404
    assert stranger.patch(f"/activities/{plan['id']}", json={"name": "Mine"}).status_code == 404
    assert stranger.post(f"/activities/{plan['id']}/move", json={"direction": "up"}).status_code == 404
    assert stranger.delete(f"/activities/{plan['id']}").status_code == 404
    assert stranger.post(f"/gaps/{req}/dismiss").status_code == 404

    session.expire_all()
    assert session.get(Activity, plan["id"]).name == "Castle"
    assert len(session.exec(select(Gap).where(Gap.trip_id == trip_id, Gap.origin == "request")).all()) == 1


def test_removing_a_request_cancels_its_queued_research(make_client, engine):
    """Research costs money: a request removed before the worker picks it up must never run."""
    client = make_client()
    trip_id = _confirm(client)
    day = _board(client, trip_id)["days"][0]["id"]
    out = client.post(f"/days/{day}/plan-requests", json={"request": "Dinner"}).json()
    assert client.post(f"/gaps/{out['gap_id']}/dismiss").status_code == 204

    with Session(engine) as s:
        job = s.get(ResearchJob, out["job_id"])
        assert (job.status, job.error) == ("failed", "This request was removed.")
        assert claim_job(s) is None


def test_worker_skips_research_for_a_removed_request(make_client, engine):
    """Backstop: even if a job was claimed first, a removed request never reaches the paid runner."""
    client = make_client()
    trip_id = _confirm(client)
    day = _board(client, trip_id)["days"][0]["id"]
    out = client.post(f"/days/{day}/plan-requests", json={"request": "Dinner"}).json()
    calls = []
    with Session(engine) as s:
        job = claim_job(s)
        gap = s.get(Gap, out["gap_id"])
        gap.status = "dismissed"
        s.add(gap)
        s.commit()
        run_job(s, job, runner=lambda ctx: calls.append(ctx), fetch=lambda p: [])
        assert calls == []
        assert s.get(ResearchJob, out["job_id"]).status == "failed"
