"""Agent cost ledger: recording runs and rolling them up for the admin view."""
from sqlmodel import Session

from app.agents.usage import Usage
from app.models import AgentRun


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
