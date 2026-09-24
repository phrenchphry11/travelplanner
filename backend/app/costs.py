"""Agent cost ledger: recording runs and rolling them up for the admin view."""
from datetime import datetime, timedelta

from sqlalchemy import case, func
from sqlmodel import Session, select

from app.agents.usage import Usage
from app.models import AgentRun, Trip, User, utcnow


def record_agent_run(
    session: Session,
    kind: str,
    usage: Usage,
    *,
    user_id: str,
    ok: bool = True,
    trip_id: str | None = None,
    intake_session_id: str | None = None,
    research_job_id: str | None = None,
) -> AgentRun:
    """Add a ledger row for one run. Caller commits."""
    run = AgentRun(
        kind=kind,
        ok=ok,
        user_id=user_id,
        trip_id=trip_id,
        intake_session_id=intake_session_id,
        research_job_id=research_job_id,
        model=usage.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        searches=usage.searches,
        cost_usd=usage.cost_usd(),
    )
    session.add(run)
    return run


# ---- Rollups for the admin view ----------------------------------------------

def _totals(session: Session, since: datetime | None = None) -> dict:
    q = select(
        func.count(AgentRun.id),
        func.coalesce(func.sum(case((AgentRun.ok.is_(False), 1), else_=0)), 0),
        func.coalesce(func.sum(AgentRun.searches), 0),
        func.coalesce(func.sum(AgentRun.cost_usd), 0.0),
        func.coalesce(func.sum(case((AgentRun.kind == "intake", AgentRun.cost_usd), else_=0.0)), 0.0),
        func.coalesce(func.sum(case((AgentRun.kind == "research", AgentRun.cost_usd), else_=0.0)), 0.0),
    )
    if since is not None:
        q = q.where(AgentRun.created_at >= since)
    runs, failed, searches, cost, intake, research = session.exec(q).one()
    return {
        "runs": runs,
        "failed_runs": failed,
        "searches": searches,
        "cost_usd": round(cost, 4),
        "intake_cost_usd": round(intake, 4),
        "research_cost_usd": round(research, 4),
    }


def cost_summary(session: Session, limit: int = 100, recent: int = 50) -> dict:
    """Totals, per-trip and per-user rollups, and the latest runs, costliest first."""
    trip_rows = session.exec(
        select(
            AgentRun.trip_id,
            func.count(AgentRun.id),
            func.sum(case((AgentRun.kind == "intake", 1), else_=0)),
            func.sum(case((AgentRun.kind == "research", 1), else_=0)),
            func.sum(AgentRun.searches),
            func.sum(AgentRun.cost_usd),
            func.max(AgentRun.created_at),
        )
        .where(AgentRun.trip_id.is_not(None))
        .group_by(AgentRun.trip_id)
        .order_by(func.sum(AgentRun.cost_usd).desc())
        .limit(limit)
    ).all()
    user_rows = session.exec(
        select(
            AgentRun.user_id,
            func.count(func.distinct(AgentRun.trip_id)),
            func.count(AgentRun.id),
            func.sum(AgentRun.cost_usd),
            func.max(AgentRun.created_at),
        )
        .group_by(AgentRun.user_id)
        .order_by(func.sum(AgentRun.cost_usd).desc())
        .limit(limit)
    ).all()
    recent_runs = session.exec(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(recent)).all()

    trip_ids = {r[0] for r in trip_rows} | {r.trip_id for r in recent_runs if r.trip_id}
    trips = {t.id: t for t in session.exec(select(Trip).where(Trip.id.in_(trip_ids)))} if trip_ids else {}
    user_ids = {r[0] for r in user_rows} | {r.user_id for r in recent_runs} | {t.owner_id for t in trips.values()}
    emails = {u.id: u.email for u in session.exec(select(User).where(User.id.in_(user_ids)))} if user_ids else {}

    def trip_label(trip_id: str | None) -> dict:
        trip = trips.get(trip_id) if trip_id else None
        return {
            "trip_id": trip_id,
            "title": trip.title if trip else None,  # None once purged
            "deleted": trip is None or trip.deleted_at is not None,
        }

    now = utcnow()
    return {
        "totals": {"all_time": _totals(session), "last_30_days": _totals(session, now - timedelta(days=30))},
        "trips": [
            {
                **trip_label(trip_id),
                "owner_email": emails.get(trips[trip_id].owner_id) if trip_id in trips else None,
                "runs": runs,
                "intake_turns": intake,
                "research_runs": research,
                "searches": searches,
                "cost_usd": round(cost, 4),
                "last_run_at": last,
            }
            for trip_id, runs, intake, research, searches, cost, last in trip_rows
        ],
        "users": [
            {
                "user_id": user_id,
                "email": emails.get(user_id),
                "trips": trip_count,
                "runs": runs,
                "cost_usd": round(cost, 4),
                "last_run_at": last,
            }
            for user_id, trip_count, runs, cost, last in user_rows
        ],
        "recent": [
            {
                "id": r.id,
                "created_at": r.created_at,
                "kind": r.kind,
                "ok": r.ok,
                "model": r.model,
                **trip_label(r.trip_id),
                "user_email": emails.get(r.user_id),
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "searches": r.searches,
                "cost_usd": r.cost_usd,
            }
            for r in recent_runs
        ],
    }
