from sqlmodel import Session, select

from app.models import Transit
from tests.test_choices import _confirm

CITIES = ["Lisbon", "Lisbon", "Porto"]


def _day(client, trip_id, index=0):
    return client.get(f"/trips/{trip_id}/board").json()["days"][index]["id"]


def _add(client, day_id, **fields):
    body = {"name": "Lisbon to Porto", "method": "train", **fields}
    return client.post(f"/days/{day_id}/transit", json=body)


def test_add_transit_leg(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    day_id = _day(client, trip_id)
    res = _add(client, day_id, depart_time="10:47", arrive_time="12:55", link="cp.pt", confirmation_code="ABC123", notes="Book ahead")
    assert res.status_code == 201
    out = res.json()
    assert out == {
        "id": out["id"], "day_id": day_id, "name": "Lisbon to Porto", "method": "train",
        "depart_time": "10:47", "arrive_time": "12:55", "link": "https://cp.pt",
        "confirmation_code": "ABC123", "notes": "Book ahead",
    }
    leg = session.get(Transit, out["id"])
    assert leg.depart_at.isoformat() == f"2027-05-01T10:47:00"

    board = client.get(f"/trips/{trip_id}/board").json()
    assert [t["name"] for t in board["transit"]] == ["Lisbon to Porto"]
    assert board["transit"][0]["depart_time"] == "10:47"


def test_add_transit_without_times(make_client):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    day_id = _day(client, trip_id)
    out = _add(client, day_id).json()
    assert (out["depart_time"], out["arrive_time"]) == ("", "")


def test_add_transit_validation(make_client):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    day_id = _day(client, trip_id)
    assert _add(client, day_id, name="  ").status_code == 422
    assert _add(client, day_id, depart_time="not-a-time").status_code == 422
    assert _add(client, day_id, link="javascript:alert(1)").status_code == 422
    assert client.post("/days/nope/transit", json={"name": "x"}).status_code == 404


def test_add_transit_is_private(make_client):
    owner = make_client("owner")
    trip_id = _confirm(owner, cities=CITIES)
    day_id = _day(owner, trip_id)
    stranger = make_client("stranger")
    assert _add(stranger, day_id).status_code == 404


def test_edit_transit(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    day_id = _day(client, trip_id)
    leg_id = _add(client, day_id, depart_time="10:47").json()["id"]

    out = client.patch(f"/transit/{leg_id}", json={"method": "flight", "arrive_time": "12:00"}).json()
    assert (out["method"], out["depart_time"], out["arrive_time"]) == ("flight", "10:47", "12:00")

    assert client.patch(f"/transit/{leg_id}", json={"name": "  "}).status_code == 422
    assert client.patch(f"/transit/{leg_id}", json={"depart_time": "25:99"}).status_code == 422
    assert client.patch("/transit/nope", json={"name": "x"}).status_code == 404
    stranger = make_client("stranger")
    assert stranger.patch(f"/transit/{leg_id}", json={"name": "mine now"}).status_code == 404


def test_remove_transit(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    day_id = _day(client, trip_id)
    leg_id = _add(client, day_id).json()["id"]
    assert client.delete(f"/transit/{leg_id}").status_code == 204
    assert session.get(Transit, leg_id) is None
    assert client.delete(f"/transit/{leg_id}").status_code == 404


def test_transit_is_ordered_by_departure_then_name(make_client):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    day_id = _day(client, trip_id)
    _add(client, day_id, name="Z leg no time")
    _add(client, day_id, name="Afternoon train", depart_time="14:00")
    _add(client, day_id, name="Morning train", depart_time="09:00")

    board = client.get(f"/trips/{trip_id}/board").json()
    assert [t["name"] for t in board["transit"]] == ["Morning train", "Afternoon train", "Z leg no time"]


def test_cannot_manage_transit_on_a_deleted_trip(make_client):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    day_id = _day(client, trip_id)
    leg_id = _add(client, day_id).json()["id"]
    client.delete(f"/trips/{trip_id}")

    assert _add(client, day_id).status_code == 404
    assert client.patch(f"/transit/{leg_id}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/transit/{leg_id}").status_code == 404


def test_move_transit_to_another_day_shifts_the_date_keeps_the_clock_time(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    board = client.get(f"/trips/{trip_id}/board").json()
    day0, day1 = board["days"][0]["id"], board["days"][1]["id"]
    leg_id = _add(client, day0, depart_time="10:47", arrive_time="12:55").json()["id"]

    out = client.patch(f"/transit/{leg_id}", json={"day_id": day1}).json()
    assert out["day_id"] == day1
    assert (out["depart_time"], out["arrive_time"]) == ("10:47", "12:55")  # clock time carries over

    leg = session.get(Transit, leg_id)
    assert leg.depart_at.date().isoformat() == board["days"][1]["date"]  # but the date itself moved


def test_move_transit_rejects_a_day_from_another_trip(make_client):
    client = make_client()
    trip_a = _confirm(client, cities=CITIES)
    trip_b = _confirm(client, cities=CITIES)
    day_a = client.get(f"/trips/{trip_a}/board").json()["days"][0]["id"]
    day_b = client.get(f"/trips/{trip_b}/board").json()["days"][0]["id"]
    leg_id = _add(client, day_a).json()["id"]

    assert client.patch(f"/transit/{leg_id}", json={"day_id": day_b}).status_code == 409
