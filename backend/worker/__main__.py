"""Research worker.

Polls the research_jobs table for queued jobs and runs them one at a time.
The actual research agent lands in the "Research worker and job queue" epic;
for now a claimed job is marked done immediately so the loop and Render
service can be verified end to end.
"""
from __future__ import annotations

import logging
import signal
import time

from sqlalchemy import update
from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine
from app.models import Gap, ResearchJob, utcnow

log = logging.getLogger("worker")
_running = True


def _stop(*_args) -> None:
    global _running
    _running = False


def claim_job(session: Session) -> ResearchJob | None:
    job = session.exec(
        select(ResearchJob)
        .where(ResearchJob.status == "queued")
        .order_by(ResearchJob.created_at)
        .limit(1)
    ).first()
    if job is None:
        return None
    # Compare-and-set so two workers never run the same job.
    result = session.exec(
        update(ResearchJob)
        .where(ResearchJob.id == job.id, ResearchJob.status == "queued")
        .values(status="running", started_at=utcnow(), attempts=job.attempts + 1)
    )
    session.commit()
    if result.rowcount != 1:
        return None
    session.refresh(job)
    return job


def run_job(session: Session, job: ResearchJob) -> None:
    log.info("running job %s for gap %s", job.id, job.gap_id)
    # TODO(travelplanner-jdm): research agent goes here. Until then, fail the
    # job with a plain message and reopen the gap so the board shows it clearly.
    job.status = "failed"
    job.error = "Finding options isn't available yet."
    job.finished_at = utcnow()
    gap = session.get(Gap, job.gap_id)
    if gap is not None and gap.status == "researching":
        gap.status = "open"
        session.add(gap)
    session.add(job)
    session.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    poll = get_settings().worker_poll_seconds
    log.info("worker started, polling every %.1fs", poll)
    while _running:
        with Session(engine) as session:
            job = claim_job(session)
            if job is None:
                time.sleep(poll)
                continue
            try:
                run_job(session, job)
            except Exception as exc:  # noqa: BLE001
                log.exception("job %s failed", job.id)
                job.status = "failed"
                job.error = str(exc)[:2000]
                job.finished_at = utcnow()
                session.add(job)
                session.commit()
    log.info("worker stopped")


if __name__ == "__main__":
    main()
