from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200_with_envelope():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "data": {"status": "healthy"},
        "error": None,
    }
