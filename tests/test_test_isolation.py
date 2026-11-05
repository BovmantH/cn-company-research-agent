from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import httpx
import pytest

PROJECT_ROOT = Path(__file__).parents[1]


def test_collection_isolates_deployment_settings_before_application_import() -> None:
    """在新进程按真实收集顺序加载 conftest，再首次导入应用。"""
    script = dedent(
        """
        import os
        import pathlib
        import runpy
        import sys

        import dotenv
        import backend.services.mongodb as mongodb_module

        sentinels = {
            "MONGODB_URI": "mongodb://deployment.invalid/research",
            "DEEPSEEK_API_KEY": "fixture-only-not-a-real-key",
            "LLM_VENDOR": "deepseek",
            "LLM_BASE_URL_DEEPSEEK": "https://deployment.invalid/v1",
            "QCC_MCP_ENABLED": "true",
            "QCC_API_KEY": "fixture-only-not-a-real-key",
            "APP_SIGNING_SECRET": "fixture-only-signing-value",
            "ALLOWED_ORIGINS": "https://deployment.invalid",
        }
        os.environ.update(sentinels)
        os.environ["PYTHON_DOTENV_DISABLED"] = "0"
        mongo_attempts = []
        dotenv_checks = []

        def fake_mongo(*_args, **_kwargs):
            mongo_attempts.append(True)
            raise RuntimeError("test-database-connection-was-attempted")

        def fake_dotenv(*_args, **_kwargs):
            # 不读取本机 .env，只观察收集阶段是否已经禁用它。
            dotenv_checks.append(os.environ.get("PYTHON_DOTENV_DISABLED") == "1")
            return False

        original_exists = pathlib.Path.exists
        pathlib.Path.exists = lambda path: path.name == ".env" or original_exists(path)
        dotenv.load_dotenv = fake_dotenv
        mongodb_module.MongoDBService = fake_mongo
        runpy.run_path(sys.argv[1])
        import application

        assert not mongo_attempts, "collection attempted deployment Mongo initialization"
        assert dotenv_checks and all(dotenv_checks), "dotenv was not disabled before import"
        assert all(name not in os.environ for name in sentinels), "deployment config survived"
        assert not application.app.state.company_intelligence.settings.enabled
        assert application.mongodb is None
        print("collection isolation passed without file or network access")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(PROJECT_ROOT / "tests" / "conftest.py")],
        cwd=PROJECT_ROOT,
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "collection isolation passed" in completed.stdout


@pytest.mark.parametrize("operation", ["connect", "connect_ex", "create_connection"])
def test_real_socket_connections_are_blocked_by_default(operation: str) -> None:
    with socket.socket() as connection:
        connect = (
            socket.create_connection
            if operation == "create_connection"
            else getattr(connection, operation)
        )
        with pytest.raises(AssertionError, match="测试禁止真实网络"):
            connect(("203.0.113.1", 443))


def test_external_dns_is_blocked_before_any_lookup() -> None:
    with pytest.raises(AssertionError, match="测试禁止真实网络"):
        socket.getaddrinfo("model-provider.invalid", 443)


def test_in_memory_http_transport_still_works() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport) as client:
        response = client.get("https://model-provider.invalid/models")

    assert response.json() == {"ok": True}
