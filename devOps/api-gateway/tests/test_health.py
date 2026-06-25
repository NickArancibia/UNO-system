from app import app


def test_health():
    client = app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"


def test_room_list_placeholder_contract():
    client = app.test_client()
    response = client.get("/v1/room/list")
    assert response.status_code == 200
    data = response.get_json()
    assert data["result"] == "ok"
    assert data["rooms"] == []
