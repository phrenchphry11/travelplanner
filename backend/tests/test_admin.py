from datetime import timedelta

import pytest

from app.agents.usage import Usage
from app.config import get_settings
from app.costs import record_agent_run
from app.models import Trip, User, utcnow


@pytest.fixture(autouse=True)
def admin_is_boss(monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_emails", " Boss@Example.com ,other@example.com")


def _seed(session):
    for uid in ("boss", "user_a", "user_b"):
        session.add(User(id=uid, email=f"{uid}@example.com"))
    session.flush()
    kept = Trip(owner_id="user_a", title="Portugal")
    binned = Trip(owner_id="user_b", title="Japan", deleted_at=utcnow())
    session.add_all([kept, binned])
    session.flush()
    record_agent_run(session, "intake", Usage(input_tokens=1_000_000), user_id="user_a", trip_id=kept.id)  # $5
    record_agent_run(session, "research", Usage(searches=5), user_id="user_a", trip_id=kept.id)  # $0.05
    record_agent_run(session, "research", Usage(searches=100), user_id="user_b", trip_id=binned.id, ok=False)  # $1
    record_agent_run(session, "research", Usage(searches=10), user_id="user_b", trip_id="purged-trip")  # $0.10
    record_agent_run(session, "intake", Usage(output_tokens=40_000), user_id="user_b")  # $1, never confirmed
    old = record_agent_run(session, "research", Usage(searches=200), user_id="user_a", trip_id=kept.id)  # $2
    old.created_at = utcnow() - timedelta(days=45)
    session.commit()
    return kept, binned


def test_me_reports_admin_by_email_case_insensitively(make_client):
    assert make_client("boss").get("/me").json()["is_admin"] is True
    assert make_client("user_a").get("/me").json()["is_admin"] is False


def test_costs_404_for_non_admins(make_client):
    assert make_client("user_a").get("/admin/costs").status_code == 404


def test_costs_rolls_up_by_trip_and_user(make_client, session):
    kept, binned = _seed(session)
    res = make_client("boss").get("/admin/costs")
    assert res.status_code == 200
    body = res.json()

    assert body["totals"]["all_time"] == {
        "runs": 6, "failed_runs": 1, "searches": 315, "cost_usd": 9.15,
        "intake_cost_usd": 6.0, "research_cost_usd": 3.15,
    }
    assert body["totals"]["last_30_days"]["cost_usd"] == 7.15

    trips = {t["trip_id"]: t for t in body["trips"]}
    assert list(trips) == [kept.id, binned.id, "purged-trip"]  # costliest first; unconfirmed intake excluded
    assert trips[kept.id] | {"last_run_at": None} == {
        "trip_id": kept.id, "title": "Portugal", "deleted": False, "owner_email": "user_a@example.com",
        "runs": 3, "intake_turns": 1, "research_runs": 2, "searches": 205, "cost_usd": 7.05, "last_run_at": None,
    }
    assert (trips[binned.id]["title"], trips[binned.id]["deleted"]) == ("Japan", True)
    assert (trips["purged-trip"]["title"], trips["purged-trip"]["deleted"]) == (None, True)

    users = {u["user_id"]: u for u in body["users"]}
    assert users["user_a"]["cost_usd"] == 7.05
    assert (users["user_b"]["cost_usd"], users["user_b"]["trips"], users["user_b"]["runs"]) == (2.1, 2, 3)

    recent = body["recent"]
    assert len(recent) == 6
    assert recent[-1]["searches"] == 200  # oldest last
    assert {r["user_email"] for r in recent} == {"user_a@example.com", "user_b@example.com"}


def test_costs_empty_ledger(make_client):
    body = make_client("boss").get("/admin/costs").json()
    assert body["totals"]["all_time"]["cost_usd"] == 0
    assert body["trips"] == body["users"] == body["recent"] == []
