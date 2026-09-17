"""Acting on research options: choose one, say no to one, or change a pick."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth import current_user
from app.db import get_session
from app.models import Activity, Candidate, Day, Gap, Lodging, Place, TripMember, User
from app.planning import OPEN_GAP_STATUSES, TIMES_OF_DAY, lodging_coverage, next_sort_order

router = APIRouter(tags=["choices"])


def _member_candidate(session: Session, candidate_id: str, user: User) -> tuple[Candidate, Gap]:
    candidate = session.get(Candidate, candidate_id)
    if candidate is None or session.get(TripMember, (candidate.trip_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    gap = session.get(Gap, candidate.gap_id)
    if gap is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return candidate, gap


class ChoiceOut(BaseModel):
    gap_id: str
    gap_status: str
    candidate_id: str
    candidate_status: str
    resolved_by_kind: str | None
    resolved_by_id: str | None


def _out(gap: Gap, candidate: Candidate) -> ChoiceOut:
    return ChoiceOut(
        gap_id=gap.id,
        gap_status=gap.status,
        candidate_id=candidate.id,
        candidate_status=candidate.status,
        resolved_by_kind=gap.resolved_by_kind,
        resolved_by_id=gap.resolved_by_id,
    )


def _ensure_place(session: Session, candidate: Candidate) -> str:
    if candidate.place_id:
        return candidate.place_id
    payload = candidate.payload or {}
    place = Place(
        trip_id=candidate.trip_id,
        name=payload.get("name", "") or "Chosen option",
        kind="lodging",
        address=payload.get("address") or "",
        website_url=payload.get("website_url") or "",
        summary=candidate.summary,
    )
    session.add(place)
    session.flush()
    candidate.place_id = place.id
    return place.id


@router.post("/candidates/{candidate_id}/choose", response_model=ChoiceOut)
def choose_candidate(
    candidate_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ChoiceOut:
    candidate, gap = _member_candidate(session, candidate_id, user)
    if gap.status not in OPEN_GAP_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "Something is already chosen here. Change it first.")
    if candidate.status != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, "This option isn't available to choose.")

    payload = candidate.payload or {}
    link = payload.get("booking_url") or payload.get("website_url") or ""

    if gap.kind == "lodging":
        days = list(session.exec(select(Day).where(Day.trip_id == gap.trip_id).order_by(Day.date)))
        nights = lodging_coverage(gap, days)
        if not nights:
            raise HTTPException(status.HTTP_409_CONFLICT, "There are no nights to book for this stay.")
        place_id = _ensure_place(session, candidate)
        item = Lodging(
            trip_id=gap.trip_id,
            place_id=place_id,
            check_in=nights[0].date,
            check_out=nights[-1].date + timedelta(days=1),
            booking_url=link,
            status="planned",
            notes=payload.get("price_range") or "",
        )
        kind = "lodging"
    elif gap.kind == "activity":
        if gap.day_id is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "This isn't tied to a day.")
        best_time = payload.get("best_time")
        item = Activity(
            trip_id=gap.trip_id,
            day_id=gap.day_id,
            name=payload.get("name", "") or "Plan",
            kind=payload.get("activity_kind") or "other",
            place_id=candidate.place_id,
            # The traveler's own "in the evening" beats the option's best time.
            time_of_day=gap.time_of_day or (best_time if best_time in TIMES_OF_DAY else ""),
            booking_url=link,
            status="planned",
            notes=candidate.summary,
            sort_order=next_sort_order(session, gap.day_id),
        )
        kind = "activity"
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, "Choosing isn't supported for this kind of item yet.")

    session.add(item)
    session.flush()
    candidate.status = "accepted"
    gap.status = "answered"
    gap.resolved_by_kind = kind
    gap.resolved_by_id = item.id
    session.add_all([candidate, gap])
    session.commit()
    return _out(gap, candidate)


class RejectRequest(BaseModel):
    reason: str = Field(default="", max_length=300)


@router.post("/candidates/{candidate_id}/reject", response_model=ChoiceOut)
def reject_candidate(
    candidate_id: str,
    body: RejectRequest | None = None,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ChoiceOut:
    candidate, gap = _member_candidate(session, candidate_id, user)
    if candidate.status != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, "This option can't be hidden.")
    candidate.status = "rejected"
    candidate.rejection_reason = (body.reason.strip() if body else "")
    session.add(candidate)
    session.commit()
    return _out(gap, candidate)


@router.post("/candidates/{candidate_id}/restore", response_model=ChoiceOut)
def restore_candidate(
    candidate_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ChoiceOut:
    candidate, gap = _member_candidate(session, candidate_id, user)
    if candidate.status != "rejected":
        raise HTTPException(status.HTTP_409_CONFLICT, "This option isn't hidden.")
    candidate.status = "proposed"
    candidate.rejection_reason = ""
    session.add(candidate)
    session.commit()
    return _out(gap, candidate)


def undo_choice(session: Session, gap: Gap) -> Candidate | None:
    """Delete the plan item an answered gap created and put its options back. Doesn't commit."""
    model = {"lodging": Lodging, "activity": Activity}.get(gap.resolved_by_kind or "")
    if model is not None and gap.resolved_by_id:
        item = session.get(model, gap.resolved_by_id)
        if item is not None:
            session.delete(item)
            session.flush()

    chosen = session.exec(
        select(Candidate).where(Candidate.gap_id == gap.id, Candidate.status == "accepted")
    ).first()
    if chosen is not None:
        chosen.status = "proposed"
        session.add(chosen)

    gap.status = "open"
    gap.resolved_by_kind = None
    gap.resolved_by_id = None
    session.add(gap)
    return chosen


@router.post("/gaps/{gap_id}/reopen", response_model=ChoiceOut)
def reopen_gap(
    gap_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> ChoiceOut:
    gap = session.get(Gap, gap_id)
    if gap is None or session.get(TripMember, (gap.trip_id, user.id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if gap.status != "answered":
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is chosen here yet.")
    chosen = undo_choice(session, gap)
    session.commit()
    return ChoiceOut(
        gap_id=gap.id, gap_status=gap.status,
        candidate_id=chosen.id if chosen else "", candidate_status=chosen.status if chosen else "",
        resolved_by_kind=None, resolved_by_id=None,
    )
