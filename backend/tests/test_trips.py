from app.models import Gap


def test_list_starts_empty(make_client):
    assert make_client().get("/trips").json() == []


def test_create_and_list_trip(make_client):
    client = make_client()
    res = client.post("/trips", json={"title": "  Portugal  ", "start_date": "2027-05-01", "end_date": "2027-05-10"})
    assert res.status_code == 201
    trip = res.json()
    assert trip["title"] == "Portugal"
    assert trip["status"] == "dreaming"
    assert trip["open_gap_count"] == 0
    assert [t["id"] for t in client.get("/trips").json()] == [trip["id"]]


def test_rejects_blank_title_and_backwards_dates(make_client):
    client = make_client()
    assert client.post("/trips", json={"title": "   "}).status_code == 422
    res = client.post("/trips", json={"title": "x", "start_date": "2027-05-10", "end_date": "2027-05-01"})
    assert res.status_code == 422


def test_open_gap_count_ignores_answered_gaps(make_client, session):
    client = make_client()
    trip_id = client.post("/trips", json={"title": "Lisbon"}).json()["id"]
    session.add_all([
        Gap(trip_id=trip_id, kind="lodging", prompt="a", status="open"),
        Gap(trip_id=trip_id, kind="activity", prompt="b", status="researching"),
        Gap(trip_id=trip_id, kind="activity", prompt="c", status="answered"),
    ])
    session.commit()
    assert client.get("/trips").json()[0]["open_gap_count"] == 2
    assert client.get(f"/trips/{trip_id}").json()["open_gap_count"] == 2


def test_other_users_cannot_see_or_delete_trip(make_client):
    owner = make_client("owner")
    trip_id = owner.post("/trips", json={"title": "Private"}).json()["id"]
    stranger = make_client("stranger")
    assert stranger.get("/trips").json() == []
    assert stranger.get(f"/trips/{trip_id}").status_code == 404
    assert stranger.delete(f"/trips/{trip_id}").status_code == 404


def test_owner_can_delete_trip_with_children(make_client, session):
    client = make_client()
    trip_id = client.post("/trips", json={"title": "Gone"}).json()["id"]
    session.add(Gap(trip_id=trip_id, kind="lodging", prompt="x"))
    session.commit()
    assert client.delete(f"/trips/{trip_id}").status_code == 204
    assert client.get(f"/trips/{trip_id}").status_code == 404
    assert client.get("/trips").json() == []


def test_members_can_change_status_and_it_persists(make_client):
    owner = make_client("owner")
    trip_id = owner.post("/trips", json={"title": "Portugal"}).json()["id"]
    res = owner.patch(f"/trips/{trip_id}", json={"status": "booked"})
    assert res.status_code == 200 and res.json()["status"] == "booked"
    assert owner.get(f"/trips/{trip_id}").json()["status"] == "booked"
    assert owner.get("/trips").json()[0]["status"] == "booked"

    editor = make_client("editor")
    editor.get("/me")  # has signed in before, so the invite adds them right away
    owner.post(f"/trips/{trip_id}/collaborators", json={"email": "editor@example.com"})
    assert editor.patch(f"/trips/{trip_id}", json={"status": "done"}).json()["status"] == "done"


def test_status_change_rejects_unknown_values_and_strangers(make_client):
    owner = make_client("owner")
    trip_id = owner.post("/trips", json={"title": "Portugal"}).json()["id"]
    assert owner.patch(f"/trips/{trip_id}", json={"status": "cancelled"}).status_code == 422
    assert make_client("stranger").patch(f"/trips/{trip_id}", json={"status": "done"}).status_code == 404
    owner.delete(f"/trips/{trip_id}")
    assert owner.patch(f"/trips/{trip_id}", json={"status": "done"}).status_code == 404  # in the trash
    assert owner.get("/trips?deleted=true").json()[0]["status"] == "dreaming"
