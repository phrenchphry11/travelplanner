"""Plan rules shared by the board and choice endpoints."""
from app.models import Day, Gap


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
