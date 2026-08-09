from __future__ import annotations

from typing import Any

import pytest

import backend.services.mongodb as mongodb_module
from backend.services.mongodb import MongoDBService


class FakeAdmin:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.commands: list[str] = []

    def command(self, name: str) -> dict[str, int]:
        self.commands.append(name)
        if self.error is not None:
            raise self.error
        return {"ok": 1}


class FakeDatabase:
    def __init__(self) -> None:
        self.jobs = object()
        self.reports = object()


class FakeMongoClient:
    instance: "FakeMongoClient | None" = None
    admin_error: Exception | None = None

    def __init__(self, uri: str, **options: Any) -> None:
        self.uri = uri
        self.options = options
        self.admin = FakeAdmin(self.admin_error)
        self.database = FakeDatabase()
        self.default_database_fallback: str | None = None
        FakeMongoClient.instance = self

    def get_default_database(self, default: str | None = None) -> FakeDatabase:
        self.default_database_fallback = default
        return self.database


def test_initialization_pings_and_uses_uri_default_database(monkeypatch) -> None:
    FakeMongoClient.admin_error = None
    monkeypatch.setattr(mongodb_module, "MongoClient", FakeMongoClient)

    service = MongoDBService("mongodb://localhost/custom_database")

    client = FakeMongoClient.instance
    assert client is not None
    assert client.admin.commands == ["ping"]
    assert client.default_database_fallback == "tavily_research"
    assert service.db is client.database


def test_initialization_propagates_ping_failure(monkeypatch) -> None:
    FakeMongoClient.admin_error = ConnectionError("unreachable")
    monkeypatch.setattr(mongodb_module, "MongoClient", FakeMongoClient)

    with pytest.raises(ConnectionError, match="unreachable"):
        MongoDBService("mongodb://unreachable")
