from app.card_catalog import CARD_CATALOG


def test_card_catalog(make_client):
    res = make_client().get("/cards/catalog")
    assert res.status_code == 200
    assert res.json()["catalog"] == CARD_CATALOG


def test_cards_default_empty(make_client):
    assert make_client().get("/me/cards").json() == {"cards": []}


def test_set_cards_replaces_list(make_client):
    client = make_client()
    res = client.put("/me/cards", json={"cards": ["Chase Sapphire Reserve", "Marriott Bonvoy"]})
    assert res.status_code == 200
    assert res.json()["cards"] == ["Chase Sapphire Reserve", "Marriott Bonvoy"]
    assert client.get("/me/cards").json()["cards"] == ["Chase Sapphire Reserve", "Marriott Bonvoy"]

    res2 = client.put("/me/cards", json={"cards": ["Amex Platinum"]})
    assert res2.json()["cards"] == ["Amex Platinum"]
    assert client.get("/me/cards").json()["cards"] == ["Amex Platinum"]


def test_set_cards_strips_blanks_and_dedupes_case_insensitively(make_client):
    client = make_client()
    res = client.put("/me/cards", json={"cards": [" Chase Sapphire Reserve ", "", "chase sapphire reserve", "  "]})
    assert res.json()["cards"] == ["Chase Sapphire Reserve"]


def test_cards_are_scoped_to_their_owner(make_client):
    make_client("user_a").put("/me/cards", json={"cards": ["Amex Platinum"]})
    assert make_client("user_b").get("/me/cards").json()["cards"] == []


def test_set_cards_rejects_too_many(make_client):
    res = make_client().put("/me/cards", json={"cards": [f"Card {i}" for i in range(31)]})
    assert res.status_code == 422
