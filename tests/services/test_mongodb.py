from __future__ import annotations

from datetime import timedelta
from typing import Any

import certifi
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
        self.jobs = FakeCollection()
        self.reports = FakeCollection()


class FakeCollection:
    def __init__(self) -> None:
        self.document: dict[str, Any] | None = None

    def find_one(self, _query: dict[str, str]) -> dict[str, Any] | None:
        return self.document

    def insert_one(self, document: dict[str, Any]) -> None:
        self.document = document

    def update_one(
        self,
        _query: dict[str, str],
        update: dict[str, dict[str, Any]],
    ) -> None:
        if self.document is not None:
            self.document.update(update["$set"])


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


def test_plain_mongodb_uri_does_not_implicitly_enable_tls(monkeypatch) -> None:
    FakeMongoClient.admin_error = None
    monkeypatch.setattr(mongodb_module, "MongoClient", FakeMongoClient)

    MongoDBService("mongodb://localhost:27017/company_research")

    client = FakeMongoClient.instance
    assert client is not None
    assert "tlsCAFile" not in client.options


def test_initialization_preserves_timezone_information_on_reads(monkeypatch) -> None:
    FakeMongoClient.admin_error = None
    monkeypatch.setattr(mongodb_module, "MongoClient", FakeMongoClient)

    MongoDBService("mongodb://localhost:27017/company_research")

    client = FakeMongoClient.instance
    assert client is not None
    assert client.options["tz_aware"] is True


@pytest.mark.parametrize(
    "uri",
    [
        "mongodb://database.example/company_research?tls=true",
        "mongodb+srv://database.example/company_research",
    ],
)
def test_tls_mongodb_uri_uses_certifi_ca(uri: str, monkeypatch) -> None:
    FakeMongoClient.admin_error = None
    monkeypatch.setattr(mongodb_module, "MongoClient", FakeMongoClient)

    MongoDBService(uri)

    client = FakeMongoClient.instance
    assert client is not None
    assert client.options["tlsCAFile"] == certifi.where()


def test_get_job_hides_internal_mongo_id_without_mutating_document(monkeypatch) -> None:
    FakeMongoClient.admin_error = None
    monkeypatch.setattr(mongodb_module, "MongoClient", FakeMongoClient)
    service = MongoDBService("mongodb://localhost/company_research")
    stored = {"_id": object(), "job_id": "job-1", "status": "completed"}
    service.jobs.document = stored

    result = service.get_job("job-1")

    assert result == {"job_id": "job-1", "status": "completed"}
    assert "_id" in stored


def test_get_report_hides_internal_mongo_id_without_mutating_document(
    monkeypatch,
) -> None:
    FakeMongoClient.admin_error = None
    monkeypatch.setattr(mongodb_module, "MongoClient", FakeMongoClient)
    service = MongoDBService("mongodb://localhost/company_research")
    stored = {"_id": object(), "job_id": "job-1", "report_content": "报告"}
    service.reports.document = stored

    result = service.get_report("job-1")

    assert result == {"job_id": "job-1", "report_content": "报告"}
    assert "_id" in stored


def test_create_job_stores_timezone_aware_utc_timestamps(monkeypatch) -> None:
    FakeMongoClient.admin_error = None
    monkeypatch.setattr(mongodb_module, "MongoClient", FakeMongoClient)
    service = MongoDBService("mongodb://localhost/company_research")

    service.create_job("job-1", {"company": "示例科技"})

    job = service.get_job("job-1")
    assert job is not None
    assert job["created_at"].utcoffset() == timedelta(0)
    assert job["updated_at"].utcoffset() == timedelta(0)


def test_update_job_stores_timezone_aware_utc_timestamp(monkeypatch) -> None:
    FakeMongoClient.admin_error = None
    monkeypatch.setattr(mongodb_module, "MongoClient", FakeMongoClient)
    service = MongoDBService("mongodb://localhost/company_research")
    service.create_job("job-1", {"company": "示例科技"})

    service.update_job("job-1", status="completed")

    job = service.get_job("job-1")
    assert job is not None
    assert job["updated_at"].utcoffset() == timedelta(0)


def test_store_report_stores_timezone_aware_utc_timestamp(monkeypatch) -> None:
    FakeMongoClient.admin_error = None
    monkeypatch.setattr(mongodb_module, "MongoClient", FakeMongoClient)
    service = MongoDBService("mongodb://localhost/company_research")

    service.store_report("job-1", {"report": "示例报告"})

    report = service.get_report("job-1")
    assert report is not None
    assert report["created_at"].utcoffset() == timedelta(0)


def test_initialization_propagates_ping_failure(monkeypatch) -> None:
    FakeMongoClient.admin_error = ConnectionError("unreachable")
    monkeypatch.setattr(mongodb_module, "MongoClient", FakeMongoClient)

    with pytest.raises(ConnectionError, match="unreachable"):
        MongoDBService("mongodb://unreachable")
