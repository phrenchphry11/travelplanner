from sqlmodel import select

from app.geocoding import get_trip_locator
from app.main import app
from app.models import Gap

CITIES = ["Lisbon", "Lisbon", "Porto", "Porto"]


def _confirm(client, cities=CITIES):
    body = {
        "title": "Portugal",
        "start_date": "2027-05-01",
        "destinations": ["Portugal"],
        "days": [{"base_city": c, "title": c} for c in cities],
    }
    res = client.post("/intake/confirm", json=body)
    assert res.status_code == 201
    return res.json()["id"]


def test_confirm_triggers_locator_and_board_reports_locating(make_client):
    client = make_client()
    located = []
    app.dependency_overrides[get_trip_locator] = lambda: located.append
    trip_id = _confirm(client)
    assert located == [trip_id]

    board = client.get(f"/trips/{trip_id}/board").json()
    assert located == [trip_id, trip_id]  # still unlocated, so the board retries
    assert {p["name"]: p["locating"] for p in board["places"]} == {"Lisbon": True, "Porto": True}


def test_board_shape_and_lodging_coverage(make_client):
    client = make_client()
    trip_id = _confirm(client)
    board = client.get(f"/trips/{trip_id}/board").json()

    assert board["trip"]["open_gap_count"] == 6
    assert [d["date"] for d in board["days"]] == ["2027-05-01", "2027-05-02", "2027-05-03", "2027-05-04"]
    day_ids = [d["id"] for d in board["days"]]

    lodging = {g["prompt"]: g["covers_day_ids"] for g in board["gaps"] if g["kind"] == "lodging"}
    assert lodging == {
        "Where to stay in Lisbon (May 1–2, 2 nights)": day_ids[0:2],
        "Where to stay in Porto (May 3, 1 night)": [day_ids[2]],  # May 4 is departure
    }
    activity = [g for g in board["gaps"] if g["kind"] == "activity"]
    assert [g["covers_day_ids"] for g in activity] == [[d] for d in day_ids]
    assert all(g["job"] is None for g in board["gaps"])
    assert board["lodgings"] == [] and board["activities"] == []


def test_board_is_private(make_client):
    trip_id = _confirm(make_client("owner"))
    assert make_client("stranger").get(f"/trips/{trip_id}/board").status_code == 404


def test_cards_nudge_shows_with_no_cards_and_hides_once_added(make_client):
    client = make_client()
    trip_id = _confirm(client)
    assert client.get(f"/trips/{trip_id}/board").json()["show_cards_nudge"] is True

    client.put("/me/cards", json={"cards": ["Chase Sapphire Reserve"]})
    assert client.get(f"/trips/{trip_id}/board").json()["show_cards_nudge"] is False


def test_cards_nudge_sticks_dismissed(make_client):
    client = make_client()
    trip_id = _confirm(client)
    assert client.post("/me/cards/dismiss-nudge").status_code == 204
    assert client.get(f"/trips/{trip_id}/board").json()["show_cards_nudge"] is False

    # Idempotent: dismissing again doesn't error.
    assert client.post("/me/cards/dismiss-nudge").status_code == 204


def test_cards_nudge_hidden_with_no_open_lodging_or_activity_gaps(make_client, session):
    client = make_client()
    trip_id = _confirm(client)
    for gap in session.exec(select(Gap).where(Gap.trip_id == trip_id)):
        gap.status = "answered"
        session.add(gap)
    session.commit()
    assert client.get(f"/trips/{trip_id}/board").json()["show_cards_nudge"] is False


def test_start_research_is_idempotent_and_visible_on_board(make_client):
    client = make_client()
    trip_id = _confirm(client)
    gap_id = client.get(f"/trips/{trip_id}/board").json()["gaps"][0]["id"]

    first = client.post(f"/gaps/{gap_id}/research")
    assert first.status_code == 202
    second = client.post(f"/gaps/{gap_id}/research")
    assert second.json()["id"] == first.json()["id"]

    gap = next(g for g in client.get(f"/trips/{trip_id}/board").json()["gaps"] if g["id"] == gap_id)
    assert gap["status"] == "researching"
    assert gap["job"]["status"] == "queued"


def test_start_research_rejects_strangers_and_filled_gaps(make_client, session):
    owner = make_client("owner")
    trip_id = _confirm(owner)
    gap_id = owner.get(f"/trips/{trip_id}/board").json()["gaps"][0]["id"]
    assert make_client("stranger").post(f"/gaps/{gap_id}/research").status_code == 404
    assert owner.post("/gaps/nope/research").status_code == 404

    gap = session.get(Gap, gap_id)
    gap.status = "answered"
    session.add(gap)
    session.commit()
    assert owner.post(f"/gaps/{gap_id}/research").status_code == 409
