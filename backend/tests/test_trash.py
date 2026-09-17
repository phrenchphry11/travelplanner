from datetime import timedelta

from sqlmodel import Session, select

from app.models import ResearchJob, Trip, utcnow
from app.trash import PURGE_AFTER, purge_deleted_trips
from tests.test_choices import _confirm, _lodging_gap
from worker.__main__ import build_context

CITIES = ["Lisbon", "Lisbon", "Porto"]


def test_deleting_a_trip_soft_deletes_it(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    assert client.delete(f"/trips/{trip_id}").status_code == 204

    trip = session.get(Trip, trip_id)
    assert trip is not None and trip.deleted_at is not None  # still in the database


def test_deleted_trip_disappears_from_every_read_path(make_client):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    client.delete(f"/trips/{trip_id}")

    assert client.get("/trips").json() == []
    assert client.get(f"/trips/{trip_id}").status_code == 404
    assert client.get(f"/trips/{trip_id}/board").status_code == 404
    assert client.get(f"/trips/{trip_id}/days").status_code == 404
    assert client.delete(f"/trips/{trip_id}").status_code == 404  # can't delete twice


def test_deleted_trip_appears_only_in_the_trash_listing(make_client):
    client = make_client()
    kept_id = _confirm(client, cities=CITIES)
    trashed_id = _confirm(client, cities=CITIES)
    client.delete(f"/trips/{trashed_id}")

    assert [t["id"] for t in client.get("/trips").json()] == [kept_id]
    trashed = client.get("/trips?deleted=true").json()
    assert [t["id"] for t in trashed] == [trashed_id]
    assert trashed[0]["deleted_at"] is not None


def test_only_the_owner_can_delete_or_restore(make_client):
    owner = make_client("owner")
    trip_id = _confirm(owner, cities=CITIES)
    stranger = make_client("stranger")
    assert stranger.delete(f"/trips/{trip_id}").status_code == 404

    owner.delete(f"/trips/{trip_id}")
    assert stranger.post(f"/trips/{trip_id}/restore").status_code == 404


def test_restore_brings_a_trip_back(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    client.delete(f"/trips/{trip_id}")

    res = client.post(f"/trips/{trip_id}/restore")
    assert res.status_code == 200
    assert res.json()["deleted_at"] is None
    assert session.get(Trip, trip_id).deleted_at is None
    assert [t["id"] for t in client.get("/trips").json()] == [trip_id]
    assert client.get(f"/trips/{trip_id}/board").status_code == 200

    assert client.post(f"/trips/{trip_id}/restore").status_code == 404  # not in the trash any more


def test_cannot_start_research_on_a_deleted_trip(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    gap = _lodging_gap(client, trip_id)
    client.delete(f"/trips/{trip_id}")

    assert client.post(f"/gaps/{gap['id']}/research").status_code == 404


def test_worker_refuses_to_research_a_deleted_trip(make_client, session):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    gap = _lodging_gap(client, trip_id)
    client.post(f"/gaps/{gap['id']}/research")
    job = session.exec(select(ResearchJob).where(ResearchJob.trip_id == trip_id)).one()

    trip = session.get(Trip, trip_id)
    trip.deleted_at = utcnow()
    session.add(trip)
    session.commit()

    import pytest
    from app.agents.research import ResearchError

    with pytest.raises(ResearchError, match="deleted"):
        build_context(session, job)


def test_purge_removes_only_trips_deleted_long_enough_ago(make_client, session, engine):
    client = make_client()
    old_id = _confirm(client, cities=CITIES)
    recent_id = _confirm(client, cities=["Lisbon"])
    client.delete(f"/trips/{old_id}")
    client.delete(f"/trips/{recent_id}")

    old_trip = session.get(Trip, old_id)
    old_trip.deleted_at = utcnow() - PURGE_AFTER - timedelta(days=1)
    session.add(old_trip)
    session.commit()

    with Session(engine) as s:
        purged = purge_deleted_trips(s)
    assert purged == 1
    session.expire_all()
    assert session.get(Trip, old_id) is None  # gone for good
    assert session.get(Trip, recent_id) is not None  # still in the trash, not old enough


def test_purge_removes_children_first(make_client, session, engine):
    """A purged trip's gaps, places, etc. must not be left orphaned."""
    from sqlmodel import select as sel

    from app.models import Gap, Place

    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    client.delete(f"/trips/{trip_id}")
    trip = session.get(Trip, trip_id)
    trip.deleted_at = utcnow() - PURGE_AFTER - timedelta(days=1)
    session.add(trip)
    session.commit()

    with Session(engine) as s:
        purge_deleted_trips(s)

    session.expire_all()
    assert session.exec(sel(Gap).where(Gap.trip_id == trip_id)).first() is None
    assert session.exec(sel(Place).where(Place.trip_id == trip_id)).first() is None


def test_deleted_trip_is_never_publicly_shared(make_client):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    slug = client.post(f"/trips/{trip_id}/share").json()["share_slug"]
    assert client.get(f"/share/{slug}").status_code == 200

    client.delete(f"/trips/{trip_id}")
    assert client.get(f"/share/{slug}").status_code == 404


def test_cannot_manage_sharing_on_a_deleted_trip(make_client):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    client.delete(f"/trips/{trip_id}")
    assert client.post(f"/trips/{trip_id}/share").status_code == 404


def test_cannot_reopen_a_gap_on_a_deleted_trip(make_client):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    gap = _lodging_gap(client, trip_id)
    client.post(f"/gaps/{gap['id']}/lodging", json={"name": "My Aunt's Flat"})
    client.delete(f"/trips/{trip_id}")

    assert client.post(f"/gaps/{gap['id']}/reopen").status_code == 404


def test_cannot_rename_a_day_on_a_deleted_trip(make_client):
    client = make_client()
    trip_id = _confirm(client, cities=CITIES)
    day_id = client.get(f"/trips/{trip_id}/board").json()["days"][0]["id"]
    client.delete(f"/trips/{trip_id}")
    assert client.patch(f"/days/{day_id}", json={"title": "x"}).status_code == 404
