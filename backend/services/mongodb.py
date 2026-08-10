from datetime import datetime
from typing import Any, Dict, Optional

import certifi
from pymongo import MongoClient


class MongoDBService:
    def __init__(self, uri: str):
        """连接并探测 MongoDB；URI 未指定数据库时回退到历史默认库。"""
        # 使用 certifi 提供的证书执行 SSL 校验
        self.client = MongoClient(
            uri, tlsCAFile=certifi.where(), retryWrites=True, w="majority"
        )
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
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
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
        update_data = {"updated_at": datetime.utcnow()}
        if status:
            update_data["status"] = status
        if result:
            update_data["result"] = result
        if error:
            update_data["error"] = error

        self.jobs.update_one({"job_id": job_id}, {"$set": update_data})

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """按 ID 获取调研任务。"""
        return self.jobs.find_one({"job_id": job_id})

    def store_report(self, job_id: str, report_data: Dict[str, Any]) -> None:
        """保存最终调研报告。"""
        self.reports.insert_one(
            {
                "job_id": job_id,
                "report_content": report_data.get("report", ""),
                "references": report_data.get("references", []),
                "sections": report_data.get("sections_completed", []),
                "analyst_queries": report_data.get("analyst_queries", {}),
                "created_at": datetime.utcnow(),
            }
        )

    def get_report(self, job_id: str) -> Optional[Dict[str, Any]]:
        """按任务 ID 获取报告。"""
        return self.reports.find_one({"job_id": job_id})
