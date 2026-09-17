"""Plan rules shared by the board, trips, choice, and plan endpoints."""
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from sqlmodel import Session, select

from app.models import Activity, Day, Gap, Trip

OPEN_GAP_STATUSES = ("open", "researching")


def trip_is_deleted(session: Session, trip_id: str) -> bool:
    """True if the trip is missing or in the trash. Sub-resource endpoints (a day, an
    activity, a gap, a saved place, ...) check this alongside their own membership check,
    since a trip's membership row outlives the trip being soft-deleted."""
    trip = session.get(Trip, trip_id)
    return trip is None or trip.deleted_at is not None

TIMES_OF_DAY = ("morning", "afternoon", "evening")

_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?!\d)")  # "mailto:" but not "example.com:8080"


def clean_link(value: str) -> str:
    """'example.com/tour' -> 'https://example.com/tour'. Only web links are kept."""
    value = value.strip()
    if not value:
        return ""
    if _SCHEME.match(value) and not value.lower().startswith(("http://", "https://")):
        raise ValueError("That link doesn't look like a web address.")  # mailto:, javascript:, ftp://
    if "://" not in value:
        value = f"https://{value}"
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or " " in value:
        raise ValueError("That link doesn't look like a web address.")
    return value


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
    return gap.status in OPEN_GAP_STATUSES and not (
        gap.kind == "activity" and gap.origin == "starter" and gap.day_id in days_with_plans
    )


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


def next_sort_order(session: Session, day_id: str, time_of_day: str = "") -> int:
    """The sort_order that puts a plan last within one time-of-day group on a day.

    Display order always sorts by (time_rank, sort_order) first, so this only
    needs to beat the other members of the same group, not the whole day.
    """
    orders = [
        a.sort_order
        for a in session.exec(select(Activity).where(Activity.day_id == day_id, Activity.time_of_day == time_of_day))
    ]
    return max(orders) + 1 if orders else 0
