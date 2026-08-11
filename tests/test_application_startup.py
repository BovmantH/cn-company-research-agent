from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import application
from backend.services.llm_factory import get_llm_credential_candidates

PROJECT_ROOT = Path(__file__).parents[1]


def test_application_can_be_imported_without_llm_key() -> None:
    env = os.environ.copy()
    env["PYTHON_DOTENV_DISABLED"] = "1"
    for key_name, _, _ in get_llm_credential_candidates():
        env.pop(key_name, None)

    completed = subprocess.run(
        [sys.executable, "-c", "import application"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_application_startup_allows_client_byok_without_server_llm_key() -> None:
    with TestClient(application.app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_application_startup_accepts_configured_llm_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "sk-opencode-test")

    with TestClient(application.app) as client:
        response = client.get("/health")

    assert response.status_code == 200


def test_application_startup_validates_explicit_vendor_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("LLM_VENDOR", "deepseek")

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY 未配置"):
        with TestClient(application.app):
            pass


def test_application_startup_validates_custom_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("LLM_VENDOR_PRIORITY", "deepseek")

    with pytest.raises(RuntimeError, match="未配置任何 LLM 服务商凭证"):
        with TestClient(application.app):
            pass
