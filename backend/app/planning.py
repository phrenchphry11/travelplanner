"""Plan rules shared by the board, trips, choice, and plan endpoints."""
from collections.abc import Iterable

from sqlmodel import Session, select

from app.models import Activity, Day, Gap

OPEN_GAP_STATUSES = ("open", "researching")
TIMES_OF_DAY = ("morning", "afternoon", "evening")


def lodging_coverage(gap: Gap, days: list[Day]) -> list[Day]:
    """Nights a lodging gap covers: from its day through the end of that consecutive stay.

    `days` must be the trip's days in date order. The trip's last day is a
    departure day with no night, so it's never covered.
    """
    index = next((i for i, d in enumerate(days) if d.id == gap.day_id), None)
    if index is None:
        return []
    place_id = days[index].base_place_id
    covered = []
    for d in days[index : len(days) - 1]:
        if d.base_place_id != place_id:
            break
        covered.append(d)
    return covered


def counts_as_missing(gap: Gap, days_with_plans: set[str]) -> bool:
    """Whether a gap belongs in "What's still missing".

    Open lodging gaps and open "Find ideas" requests always count. The starter
    activity gap ("What to do in Lisbon on May 2") only stands for an empty
    day: once the day has any plan, chosen or added by hand, it stops
    counting, and it counts again if every plan is removed.
    """
    if gap.status not in OPEN_GAP_STATUSES:
        return False
    if gap.kind == "activity" and gap.origin == "starter" and gap.day_id in days_with_plans:
        return False
    return True


def days_with_plans(session: Session, trip_ids: Iterable[str]) -> set[str]:
    ids = list(trip_ids)
    if not ids:
        return set()
    return set(session.exec(select(Activity.day_id).where(Activity.trip_id.in_(ids)).distinct()))


def time_rank(time_of_day: str) -> int:
    """Morning, afternoon, evening, then anytime."""
    return TIMES_OF_DAY.index(time_of_day) if time_of_day in TIMES_OF_DAY else len(TIMES_OF_DAY)


def plan_order_key(activity: Activity) -> tuple[int, int]:
    return (time_rank(activity.time_of_day), activity.sort_order)


def ordered_day_plans(session: Session, day_id: str) -> list[Activity]:
    plans = session.exec(select(Activity).where(Activity.day_id == day_id)).all()
    return sorted(plans, key=lambda a: (*plan_order_key(a), a.id))


def next_sort_order(session: Session, day_id: str) -> int:
    orders = [a.sort_order for a in session.exec(select(Activity).where(Activity.day_id == day_id))]
    return max(orders) + 1 if orders else 0
