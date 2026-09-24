from datetime import timedelta

from sqlmodel import Session, select

from app.agents.research import CandidateIn, ResearchError, ResearchResult
from app.agents.usage import Usage
from app.models import AgentRun, Candidate, Gap, Place, ResearchJob, Source, utcnow
from worker.__main__ import claim_job, recover_stale_jobs, run_job


def _confirm(client, cities=("Lisbon", "Lisbon", "Porto")):
    body = {
        "title": "Portugal", "start_date": "2027-05-01", "destinations": ["Portugal"],
        "interests": ["food"], "travelers": 2,
        "days": [{"base_city": c, "title": f"Day in {c}"} for c in cities],
    }
    return client.post("/intake/confirm", json=body).json()["id"]


def _queue(client, trip_id, kind="lodging", nudge=""):
    board = client.get(f"/trips/{trip_id}/board").json()
    gap = next(g for g in board["gaps"] if g["kind"] == kind)
    client.post(f"/gaps/{gap['id']}/research", json={"nudge": nudge})
    return gap["id"]


def _candidate(name, **overrides):
    data = {
        "name": name, "summary": f"{name} is nice.", "pros": ["central"], "cons": ["noisy"], "confidence": "medium",
        "price_range": "€100–150 per night", "address": "Rua X 1", "neighborhood": "Baixa",
        "lat": 38.71, "lng": -9.14, "website_url": "https://x.example", "booking_url": None,
        "activity_kind": None, "best_time": None,
        "sources": [{"url": "https://x.example", "title": "X", "note": "rates"}],
    }
    data.update(overrides)
    return CandidateIn.model_validate(data)


def no_results(params):
    return []


def _run(engine, runner, fetch=no_results):
    captured = {}

    def wrapped(ctx):
        captured["ctx"] = ctx
        return runner(ctx)

    with Session(engine) as s:
        job = claim_job(s)
        assert job is not None
        job_id = job.id
        run_job(s, job, runner=wrapped, fetch=fetch)
    return job_id, captured.get("ctx")


def test_success_saves_candidates_places_sources_and_usage(make_client, engine):
    client = make_client()
    trip_id = _confirm(client)
    gap_id = _queue(client, trip_id, nudge="near the river")

    usage = Usage(input_tokens=2000, output_tokens=500, searches=4)
    result = ResearchResult(
        candidates=[_candidate("Hotel A"), _candidate("Hotel B", lat=None, lng=None, sources=[], unverified=True, confidence="low")],
        usage=usage,
    )
    job_id, ctx = _run(engine, lambda ctx: result)

    assert ctx.gap_kind == "lodging"
    assert ctx.base_city == "Lisbon"
    assert ctx.nudge == "near the river"
    assert ctx.interests == ["food"] and ctx.travelers == 2
    assert len(ctx.nearby_days) == 3  # the day itself plus up to two after (no days before)

    with Session(engine) as s:
        job = s.get(ResearchJob, job_id)
        assert job.status == "done" and job.error == ""
        assert (job.input_tokens, job.output_tokens, job.search_count) == (2000, 500, 4)
        assert job.cost_usd > 0
        assert s.get(Gap, gap_id).status == "open"
        run = s.exec(select(AgentRun)).one()
        assert (run.kind, run.ok, run.user_id, run.trip_id, run.research_job_id) == ("research", True, "user_a", trip_id, job_id)
        assert (run.searches, run.cost_usd) == (4, job.cost_usd)

        cands = s.exec(select(Candidate).where(Candidate.gap_id == gap_id).order_by(Candidate.created_at)).all()
        assert [c.payload["name"] for c in cands] == ["Hotel A", "Hotel B"]
        a_place = s.get(Place, cands[0].place_id)
        assert (a_place.kind, a_place.precision, a_place.lat) == ("lodging", "approximate", 38.71)
        assert s.get(Place, cands[1].place_id).precision == "unknown"
        assert len(s.exec(select(Source).where(Source.subject_id == cands[0].id)).all()) == 1
        assert s.exec(select(Source).where(Source.subject_id == cands[1].id)).all() == []

    board = client.get(f"/trips/{trip_id}/board").json()
    gap = next(g for g in board["gaps"] if g["id"] == gap_id)
    assert [c["name"] for c in gap["candidates"]] == ["Hotel A", "Hotel B"]
    assert gap["candidates"][0]["sources"][0]["url"] == "https://x.example"
    assert gap["candidates"][1]["unverified"] is True
    assert gap["job"]["status"] == "done"


def test_owner_cards_flow_into_lodging_and_activity_context_only(make_client, engine):
    client = make_client()
    client.put("/me/cards", json={"cards": ["Chase Sapphire Reserve"]})
    trip_id = _confirm(client)

    _queue(client, trip_id, kind="lodging")
    _, lodging_ctx = _run(engine, lambda ctx: ResearchResult([_candidate("Hotel A")], Usage()))
    assert lodging_ctx.user_cards == ["Chase Sapphire Reserve"]

    _queue(client, trip_id, kind="activity")
    _, activity_ctx = _run(engine, lambda ctx: ResearchResult([_candidate("Castle")], Usage()))
    assert activity_ctx.user_cards == ["Chase Sapphire Reserve"]


def test_perks_are_stamped_with_a_checked_date_and_reach_the_board(make_client, engine):
    client = make_client()
    client.put("/me/cards", json={"cards": ["Amex Platinum"]})
    trip_id = _confirm(client)
    gap_id = _queue(client, trip_id, kind="lodging")

    result = ResearchResult(
        candidates=[_candidate("Hotel A", perks=[
            {"card": "Amex Platinum", "note": "May be bookable through the travel portal.",
             "source_url": "https://portal.example/deal", "source_title": "Portal"},
        ])],
        usage=Usage(),
    )
    _run(engine, lambda ctx: result)

    with Session(engine) as s:
        [c] = s.exec(select(Candidate).where(Candidate.gap_id == gap_id)).all()
        [perk] = c.payload["perks"]
        assert perk["card"] == "Amex Platinum"
        assert perk["checked_date"] == utcnow().date().isoformat()

    board = client.get(f"/trips/{trip_id}/board").json()
    gap = next(g for g in board["gaps"] if g["id"] == gap_id)
    [perk] = gap["candidates"][0]["perks"]
    assert perk["source_url"] == "https://portal.example/deal"


def test_activity_place_kinds(make_client, engine):
    client = make_client()
    trip_id = _confirm(client)
    _queue(client, trip_id, kind="activity")
    result = ResearchResult(
        candidates=[_candidate("Tasca", activity_kind="meal"), _candidate("Castle", activity_kind="sight")],
        usage=Usage(),
    )
    _run(engine, lambda ctx: result)
    with Session(engine) as s:
        kinds = {p.name: p.kind for p in s.exec(select(Place).where(Place.name.in_(["Tasca", "Castle"])))}
    assert kinds == {"Tasca": "food", "Castle": "sight"}


def test_second_run_excludes_previous_and_rejected(make_client, engine):
    client = make_client()
    trip_id = _confirm(client)
    gap_id = _queue(client, trip_id)
    _run(engine, lambda ctx: ResearchResult([_candidate("Hotel A"), _candidate("Hotel B")], Usage()))

    with Session(engine) as s:
        b = s.exec(select(Candidate).where(Candidate.gap_id == gap_id)).all()[1]
        b.status, b.rejection_reason = "rejected", "too far out"
        s.add(b)
        s.commit()

    client.post(f"/gaps/{gap_id}/research")
    _, ctx = _run(engine, lambda ctx: ResearchResult([_candidate("Hotel C")], Usage()))
    assert ctx.already_suggested == ["Hotel A"]
    assert ctx.rejected == [("Hotel B", "too far out")]


def test_research_error_fails_job_and_reopens_gap(make_client, engine):
    client = make_client()
    trip_id = _confirm(client)
    gap_id = _queue(client, trip_id)

    def boom(ctx):
        raise ResearchError("The research assistant is busy right now.")

    job_id, _ = _run(engine, boom)
    board = client.get(f"/trips/{trip_id}/board").json()
    gap = next(g for g in board["gaps"] if g["id"] == gap_id)
    assert gap["status"] == "open"
    assert gap["job"] == {"id": job_id, "status": "failed", "error": "The research assistant is busy right now."}
    assert gap["candidates"] == []
    assert client.post(f"/gaps/{gap_id}/research").json()["id"] != job_id


def test_research_error_still_records_what_was_spent(make_client, engine):
    client = make_client()
    trip_id = _confirm(client)
    _queue(client, trip_id)

    def boom(ctx):
        raise ResearchError("The research assistant didn't finish in time.", Usage(input_tokens=9000, searches=5))

    job_id, _ = _run(engine, boom)
    with Session(engine) as s:
        job = s.get(ResearchJob, job_id)
        assert job.status == "failed" and job.search_count == 5 and job.cost_usd > 0
        run = s.exec(select(AgentRun)).one()
        assert (run.ok, run.trip_id, run.research_job_id, run.cost_usd) == (False, trip_id, job_id, job.cost_usd)


def test_no_candidates_is_a_failure(make_client, engine):
    client = make_client()
    trip_id = _confirm(client)
    _queue(client, trip_id)
    job_id, _ = _run(engine, lambda ctx: ResearchResult([], Usage(searches=5)))
    with Session(engine) as s:
        job = s.get(ResearchJob, job_id)
        assert job.status == "failed"
        assert "couldn't find" in job.error
        assert job.search_count == 5


def test_stale_running_jobs_are_requeued_then_failed(make_client, engine):
    client = make_client()
    trip_id = _confirm(client)
    gap_id = _queue(client, trip_id)
    with Session(engine) as s:
        job = claim_job(s)
        job.started_at = utcnow() - timedelta(minutes=30)
        s.add(job)
        s.commit()
        job_id = job.id

        recover_stale_jobs(s)
        assert s.get(ResearchJob, job_id).status == "queued"

        job = claim_job(s)  # attempt 2
        job.started_at = utcnow() - timedelta(minutes=30)
        s.add(job)
        s.commit()
        recover_stale_jobs(s)
        s.expire_all()
        job = s.get(ResearchJob, job_id)
        assert job.status == "failed" and job.attempts == 2
        assert s.get(Gap, gap_id).status == "open"


def test_nudge_is_trimmed_and_capped(make_client):
    client = make_client()
    trip_id = _confirm(client)
    gap_id = client.get(f"/trips/{trip_id}/board").json()["gaps"][0]["id"]
    assert client.post(f"/gaps/{gap_id}/research", json={"nudge": "x" * 501}).status_code == 422
