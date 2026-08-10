from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlsplit

import certifi
from pymongo import MongoClient


def _requires_certifi_ca(uri: str) -> bool:
    """判断连接字符串是否明确或按 SRV 约定启用了 TLS。"""
    parsed = urlsplit(uri)
    if parsed.scheme.lower() == "mongodb+srv":
        return True
    return any(
        key.lower() in {"tls", "ssl"} and value.lower() == "true"
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    )


class MongoDBService:
    def __init__(self, uri: str):
        """连接并探测 MongoDB；URI 未指定数据库时回退到历史默认库。"""
        options: dict[str, Any] = {
            "retryWrites": True,
            "tz_aware": True,
            "w": "majority",
        }
        if _requires_certifi_ca(uri):
            options["tlsCAFile"] = certifi.where()
        self.client = MongoClient(uri, **options)
        self.client.admin.command("ping")
        self.db = self.client.get_default_database("tavily_research")
        self.jobs = self.db.jobs
        self.reports = self.db.reports

    def create_job(self, job_id: str, inputs: Dict[str, Any]) -> None:
        """创建新的调研任务记录。"""
        self.jobs.insert_one(
            {
                "job_id": job_id,
                "inputs": inputs,
                "status": "pending",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )

    def update_job(
        self,
        job_id: str,
        status: str = None,
        result: Dict[str, Any] = None,
        error: str = None,
    ) -> None:
        """更新调研任务的结果或状态。"""
        update_data = {"updated_at": datetime.now(timezone.utc)}
        if status:
            update_data["status"] = status
        if result:
            update_data["result"] = result
        if error:
            update_data["error"] = error

        self.jobs.update_one({"job_id": job_id}, {"$set": update_data})

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 获取调研任务。"""
        document = self.jobs.find_one({"job_id": job_id})
        if document is None:
            return None
        return {key: value for key, value in document.items() if key != "_id"}

    def store_report(self, job_id: str, report_data: Dict[str, Any]) -> None:
        """保存最终调研报告。"""
        self.reports.insert_one(
            {
                "job_id": job_id,
                "report_content": report_data.get("report", ""),
                "references": report_data.get("references", []),
                "sections": report_data.get("sections_completed", []),
                "analyst_queries": report_data.get("analyst_queries", {}),
                "created_at": datetime.now(timezone.utc),
            }
        )

    def get_report(self, job_id: str) -> Optional[Dict[str, Any]]:
        """按任务 ID 获取报告。"""
        document = self.reports.find_one({"job_id": job_id})
        if document is None:
            return None
        return {key: value for key, value in document.items() if key != "_id"}
