from fastapi import FastAPI
from fastapi.testclient import TestClient

import application


def test_health_endpoint_remains_available() -> None:
    response = TestClient(application.app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "服务正常"}


def test_frontend_mount_serves_index_without_shadowing_api(tmp_path) -> None:
    frontend_dir = tmp_path / "dist"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text(
        "<!doctype html><title>公司调研助手</title>",
        encoding="utf-8",
    )
    (frontend_dir / "favicon.ico").write_bytes(b"icon")
    test_app = FastAPI()

    @test_app.get("/api/status")
    async def api_status():
        return {"status": "ok"}

    assert application.mount_frontend(test_app, frontend_dir) is True
    client = TestClient(test_app)

    assert "公司调研助手" in client.get("/").text
    assert client.get("/favicon.ico").content == b"icon"
    assert client.get("/api/status").json() == {"status": "ok"}


def test_frontend_mount_is_disabled_without_build_output(tmp_path) -> None:
    test_app = FastAPI()

    assert application.mount_frontend(test_app, tmp_path / "missing") is False
