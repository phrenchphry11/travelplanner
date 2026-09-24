from datetime import date, timedelta

import pytest
from sqlmodel import select

from app.agents.intake import (
    ChatMessage,
    DraftDay,
    IntakeError,
    IntakeResult,
    IntakeTurn,
    TripDraft,
    _build_messages,
    get_intake_runner,
)
from app.agents.usage import Usage
from app.main import app
from app.models import AgentRun, Day, Gap, IntakeSession, Place, Trip, utcnow
from app.trash import expire_unconfirmed_intake_sessions, hard_delete_trip


def _draft(cities: list[str]) -> TripDraft:
    return TripDraft(
        title="Portugal in May",
        destinations=["Portugal"],
        start_date=None,
        travelers=2,
        interests=["food"],
        days=[DraftDay(base_city=c, title=f"Day in {c}", summary="") for c in cities],
    )


@pytest.fixture
def fake_runner():
    calls = []

    def _install(result):
        def runner(history, current_draft, today):
            calls.append((history, current_draft, today))
            if isinstance(result, Exception):
                raise result
            return IntakeResult(result, Usage(input_tokens=1000, output_tokens=200, model="claude-opus-5"))

        app.dependency_overrides[get_intake_runner] = lambda: runner
        return calls

    return _install


def test_turn_returns_draft(make_client, fake_runner):
    client = make_client()
    calls = fake_runner(IntakeTurn(reply="Here's a start.", kind="draft", draft=_draft(["Lisbon", "Porto"])))
    res = client.post("/intake/turn", json={"messages": [{"role": "user", "content": "Portugal, 2 days"}]})
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "draft"
    assert [d["base_city"] for d in body["draft"]["days"]] == ["Lisbon", "Porto"]
    assert calls[0][2] == date.today()


def test_turn_passes_current_draft_and_history(make_client, fake_runner):
    client = make_client()
    calls = fake_runner(IntakeTurn(reply="When do you leave?", kind="question", draft=None))
    draft = _draft(["Lisbon"]).model_dump()
    res = client.post("/intake/turn", json={
        "messages": [
            {"role": "user", "content": "Portugal"},
            {"role": "assistant", "content": "How long?", "kind": "question"},
            {"role": "user", "content": "A week"},
        ],
        "current_draft": draft,
    })
    assert res.status_code == 200
    history, current, _ = calls[0]
    assert [m.role for m in history] == ["user", "assistant", "user"]
    assert history[1].kind == "question"
    assert current.days[0].base_city == "Lisbon"


@pytest.mark.parametrize("messages", [
    [{"role": "assistant", "content": "hi"}],
    [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}],
    [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
    [{"role": "user", "content": ""}],
])
def test_turn_rejects_malformed_conversations(make_client, fake_runner, messages):
    fake_runner(IntakeTurn(reply="x", kind="question", draft=None))
    assert make_client().post("/intake/turn", json={"messages": messages}).status_code == 422


def test_turn_surfaces_agent_errors_as_friendly_502(make_client, fake_runner):
    fake_runner(IntakeError("The trip assistant is busy right now."))
    res = make_client().post("/intake/turn", json={"messages": [{"role": "user", "content": "x"}]})
    assert res.status_code == 502
    assert res.json()["detail"] == "The trip assistant is busy right now."


def test_failed_turn_that_reached_claude_is_still_costed(make_client, fake_runner, session):
    fake_runner(IntakeError("The trip assistant gave an unexpected answer.", Usage(input_tokens=800, output_tokens=40)))
    res = make_client().post("/intake/turn", json={"messages": [{"role": "user", "content": "x"}]})
    assert res.status_code == 502
    run = session.exec(select(AgentRun)).one()
    assert (run.kind, run.ok, run.user_id, run.input_tokens) == ("intake", False, "user_a", 800)


def test_failed_turn_that_never_reached_claude_costs_nothing(make_client, fake_runner, session):
    fake_runner(IntakeError("The trip assistant is busy right now."))
    make_client().post("/intake/turn", json={"messages": [{"role": "user", "content": "x"}]})
    assert session.exec(select(AgentRun)).all() == []


def test_build_messages_appends_draft_to_last_user_turn_only():
    history = [
        ChatMessage(role="user", content="Portugal"),
        ChatMessage(role="assistant", content="How long?", kind="question"),
        ChatMessage(role="user", content="10 days"),
    ]
    msgs = _build_messages(history, _draft(["Lisbon"]))
    assert msgs[0]["content"] == "Portugal"
    assert "kind" not in msgs[1]
    assert msgs[2]["content"].startswith("10 days\n\n<current_draft>")
    assert history[2].content == "10 days"  # input not mutated


def test_turn_creates_and_resumes_session(make_client, fake_runner, session):
    client = make_client()
    fake_runner(IntakeTurn(reply="How long?", kind="question", draft=None))
    res = client.post("/intake/turn", json={"messages": [{"role": "user", "content": "Portugal"}]})
    session_id = res.json()["session_id"]
    assert session_id

    stored = session.get(IntakeSession, session_id)
    assert stored.trip_id is None
    assert [m["content"] for m in stored.messages] == ["Portugal", "How long?"]

    resumed = client.get("/intake/session").json()
    assert resumed["id"] == session_id
    assert resumed["messages"][-1]["content"] == "How long?"

    fake_runner(IntakeTurn(reply="Here's a start.", kind="draft", draft=_draft(["Lisbon"])))
    res2 = client.post("/intake/turn", json={
        "messages": [
            {"role": "user", "content": "Portugal"},
            {"role": "assistant", "content": "How long?", "kind": "question"},
            {"role": "user", "content": "A week"},
        ],
        "session_id": session_id,
    })
    assert res2.json()["session_id"] == session_id
    session.refresh(stored)
    assert len(stored.messages) == 4
    assert stored.current_draft["days"][0]["base_city"] == "Lisbon"


def test_session_get_returns_null_with_no_history(make_client):
    assert make_client().get("/intake/session").json() is None


def test_session_is_scoped_to_its_owner(make_client, fake_runner):
    fake_runner(IntakeTurn(reply="Q?", kind="question", draft=None))
    session_id = make_client("user_a").post(
        "/intake/turn", json={"messages": [{"role": "user", "content": "hi"}]}
    ).json()["session_id"]
    assert make_client("user_b").get("/intake/session").json() is None
    assert make_client("user_b").delete(f"/intake/session/{session_id}").status_code == 404


def test_discard_session_starts_over(make_client, fake_runner):
    client = make_client()
    fake_runner(IntakeTurn(reply="Q?", kind="question", draft=None))
    session_id = client.post("/intake/turn", json={"messages": [{"role": "user", "content": "hi"}]}).json()["session_id"]
    assert client.delete(f"/intake/session/{session_id}").status_code == 204
    assert client.get("/intake/session").json() is None
    assert client.delete(f"/intake/session/{session_id}").status_code == 404


def test_confirm_links_session_to_trip_and_it_no_longer_resumes(make_client, fake_runner, session):
    client = make_client()
    fake_runner(IntakeTurn(reply="Here's a start.", kind="draft", draft=_draft(["Lisbon"])))
    session_id = client.post(
        "/intake/turn", json={"messages": [{"role": "user", "content": "Portugal, a week"}]}
    ).json()["session_id"]

    trip_id = client.post(
        "/intake/confirm", json=_confirm_body(["Lisbon"], session_id=session_id)
    ).json()["id"]

    stored = session.get(IntakeSession, session_id)
    assert stored.trip_id == trip_id
    assert client.get("/intake/session").json() is None  # no longer an unconfirmed session to resume

    run = session.exec(select(AgentRun).where(AgentRun.intake_session_id == session_id)).one()
    assert (run.kind, run.ok, run.user_id, run.trip_id) == ("intake", True, "user_a", trip_id)
    assert run.model == "claude-opus-5" and run.cost_usd > 0

    trip = session.get(Trip, trip_id)
    hard_delete_trip(session, trip)
    session.commit()
    assert session.get(IntakeSession, session_id) is None  # deleted with its trip
    session.expire_all()
    assert session.get(AgentRun, run.id).trip_id == trip_id  # the cost ledger outlives the trip


def test_expire_unconfirmed_intake_sessions(make_client, fake_runner, session):
    client = make_client()
    fake_runner(IntakeTurn(reply="Q?", kind="question", draft=None))
    session_id = client.post("/intake/turn", json={"messages": [{"role": "user", "content": "hi"}]}).json()["session_id"]

    stored = session.get(IntakeSession, session_id)
    stored.updated_at = utcnow() - timedelta(days=15)
    session.add(stored)
    session.commit()

    assert expire_unconfirmed_intake_sessions(session) == 1
    assert session.get(IntakeSession, session_id) is None


def _confirm_body(cities, start="2027-05-01", **extra):
    return {
        "title": "Portugal in May",
        "start_date": start,
        "travelers": 2,
        "interests": ["food", " wine ", ""],
        "days": [{"base_city": c, "title": f"Day {i + 1}", "summary": ""} for i, c in enumerate(cities)],
        **extra,
    }


def test_confirm_creates_trip_days_places_and_gaps(make_client, session):
    client = make_client()
    cities = ["Lisbon", "Lisbon", "lisbon", "Porto", "Porto", "Porto"]
    res = client.post("/intake/confirm", json=_confirm_body(cities))
    assert res.status_code == 201
    out = res.json()
    assert out["status"] == "planning"
    assert out["start_date"] == "2027-05-01"
    assert out["end_date"] == "2027-05-06"

    trip = session.get(Trip, out["id"])
    assert trip.travelers == 2
    assert trip.interests == ["food", "wine"]

    days = session.exec(select(Day).where(Day.trip_id == trip.id).order_by(Day.date)).all()
    assert [d.date.day for d in days] == [1, 2, 3, 4, 5, 6]
    places = session.exec(select(Place).where(Place.trip_id == trip.id)).all()
    assert sorted(p.name for p in places) == ["Lisbon", "Porto"]  # case-insensitive dedupe
    assert all(p.kind == "city" for p in places)
    assert len({d.base_place_id for d in days}) == 2

    gaps = session.exec(select(Gap).where(Gap.trip_id == trip.id)).all()
    lodging = sorted((g.prompt for g in gaps if g.kind == "lodging"))
    # Lisbon May 1-3 = 3 nights; Porto May 4-5 = 2 nights (May 6 is departure).
    assert lodging == [
        "Where to stay in Lisbon (May 1–3, 3 nights)",
        "Where to stay in Porto (May 4–5, 2 nights)",
    ]
    assert sum(1 for g in gaps if g.kind == "activity") == 6
    assert out["open_gap_count"] == 8
    assert client.get("/trips").json()[0]["open_gap_count"] == 8


def test_confirm_single_day_trip_has_no_lodging_gap(make_client, session):
    client = make_client()
    out = client.post("/intake/confirm", json=_confirm_body(["Sintra"])).json()
    gaps = session.exec(select(Gap).where(Gap.trip_id == out["id"])).all()
    assert [g.kind for g in gaps] == ["activity"]


def test_confirm_final_city_only_on_departure_day_gets_no_lodging(make_client, session):
    client = make_client()
    out = client.post("/intake/confirm", json=_confirm_body(["Lisbon", "Lisbon", "Porto"])).json()
    lodging = [g.prompt for g in session.exec(select(Gap).where(Gap.trip_id == out["id"], Gap.kind == "lodging"))]
    assert lodging == ["Where to stay in Lisbon (May 1–2, 2 nights)"]


def test_confirm_date_range_across_months(make_client, session):
    client = make_client()
    out = client.post("/intake/confirm", json=_confirm_body(["Rome"] * 4, start="2027-04-29")).json()
    lodging = [g.prompt for g in session.exec(select(Gap).where(Gap.trip_id == out["id"], Gap.kind == "lodging"))]
    assert lodging == ["Where to stay in Rome (Apr 29–May 1, 3 nights)"]


@pytest.mark.parametrize("override", [
    {"start_date": None},
    {"title": "   "},
    {"days": []},
    {"days": [{"base_city": "  ", "title": "x"}]},
    {"travelers": 0},
])
def test_confirm_validation(make_client, override):
    body = _confirm_body(["Lisbon"])
    body.update(override)
    assert make_client().post("/intake/confirm", json=body).status_code == 422


def test_days_endpoint_lists_confirmed_days_with_gap_counts(make_client):
    client = make_client()
    trip_id = client.post("/intake/confirm", json=_confirm_body(["Lisbon", "Lisbon", "Porto"])).json()["id"]
    days = client.get(f"/trips/{trip_id}/days").json()
    assert [(d["date"], d["base_city"]) for d in days] == [
        ("2027-05-01", "Lisbon"), ("2027-05-02", "Lisbon"), ("2027-05-03", "Porto"),
    ]
    # Day 1 carries the Lisbon lodging gap plus its activity gap.
    assert [d["open_gap_count"] for d in days] == [2, 1, 1]
    assert make_client("stranger").get(f"/trips/{trip_id}/days").status_code == 404
