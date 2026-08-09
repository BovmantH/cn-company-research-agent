from fastapi.testclient import TestClient

from application import app


def test_configured_local_frontend_origin_is_allowed() -> None:
    response = TestClient(app).options(
        "/research",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unconfigured_origin_is_not_allowed() -> None:
    response = TestClient(app).options(
        "/research",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in response.headers
