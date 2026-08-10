import asyncio
import json
import logging
import os
import sys
import time
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.graph import Graph
from backend.services.mongodb import MongoDBService
from backend.services.pdf_service import PDFService
from backend.services.company_intelligence.runtime import CompanyIntelligenceRuntime
from backend.services.company_intelligence.mongo_ledger import MongoLedgerUnavailable
from backend.services.company_intelligence.collection import (
    PreparationKind,
    ProfessionalPreparation,
)
from backend.services.company_intelligence.requester import resolve_client_ip
from backend.services.company_intelligence.models import ProfessionalEvidence
from backend.services.company_intelligence.rendering import (
    render_professional_evidence_markdown,
)
from backend.api.company_intelligence import router as company_intelligence_router
from backend.classes.state import (
    JOB_TERMINAL_TTL_SECONDS,
    JobEventLog,
    job_status,
    prune_expired_jobs,
)

# Load environment variables from .env file at startup
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)

# 启动校验: LLMFactory 依赖至少一个 LLM provider key,缺失则直接退出,
# 避免在第一次请求时才发现 key 没配,把错误推到用户面前。
_LLM_KEY_CANDIDATES = (
    ("DEEPSEEK_API_KEY", "DeepSeek 原厂", "https://api-docs.deepseek.com/"),
    ("DASHSCOPE_API_KEY", "阿里百炼(Qwen)", "https://help.aliyun.com/zh/dashscope/"),
    ("MOONSHOT_API_KEY", "Moonshot(Kimi)", "https://platform.moonshot.cn/"),
    ("XIAOMI_API_KEY", "小米 MiMo", "https://api.xiaomimimo.com/"),
    ("OPENROUTER_API_KEY", "OpenRouter 聚合", "https://openrouter.ai/"),
    ("OPENAI_API_KEY", "OpenAI 原生(降级)", "https://platform.openai.com/"),
)
if not any(os.getenv(name) for name, _, _ in _LLM_KEY_CANDIDATES):
    # 把 stderr 切到 UTF-8,避免 Windows GBK 控制台把中文打成 mojibake
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    candidates = "\n".join(
        f"  - {name:<22}({label},见 {url})" for name, label, url in _LLM_KEY_CANDIDATES
    )
    print(
        "\n[启动失败] 未检测到 LLM provider 凭证。\n"
        "请在 .env 中至少配置以下其中一项:\n"
        f"{candidates}\n"
        "\n参考 .env.example 复制一份 .env 后填写。\n",
        file=sys.stderr,
    )
    sys.exit(1)

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
logger.addHandler(console_handler)

app = FastAPI(title="公司调研助手 API")
app.state.company_intelligence = CompanyIntelligenceRuntime.from_env()
app.state.research_tasks = set()
app.include_router(company_intelligence_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(app.state.company_intelligence.settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
pdf_service = PDFService({"pdf_output_dir": "pdfs"})
_PROFESSIONAL_COLLECTION_TIMEOUT_SECONDS = 120.0
_MAX_FINAL_REPORT_EVENT_BYTES = 14 * 1024 * 1024


# Pydantic / 请求体解析失败时,FastAPI 默认抛 422 + 英文 detail。
# 这里统一翻译成中文,保留原始 errors 字段方便前端按需展开。
_PYDANTIC_MSG_ZH = {
    "missing": "缺少必填字段",
    "value_error": "字段取值不合法",
    "type_error": "字段类型不正确",
    "string_type": "字段必须是字符串",
    "json_invalid": "请求体不是合法的 JSON",
}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body") or "body"
        zh = _PYDANTIC_MSG_ZH.get(err.get("type", ""), err.get("msg", "字段校验失败"))
        errors.append({"field": loc, "message": zh})
    summary = errors[0]["message"] if errors else "请求体校验失败"
    return JSONResponse(
        status_code=422,
        content={"detail": f"请求参数有误: {summary}", "errors": errors},
    )


mongodb = None
if mongo_uri := os.getenv("MONGODB_URI"):
    try:
        mongodb = MongoDBService(mongo_uri)
        logger.info("已启用任务与报告 MongoDB 持久化")
        try:
            app.state.company_intelligence.configure_mongo_ledger(mongodb.db)
            logger.info("已启用企业情报 MongoDB 原子用量账本")
        except MongoLedgerUnavailable:
            logger.warning("MongoDB 不支持企业情报所需事务，专业数据能力保持关闭")
    except Exception as exc:
        logger.warning(
            "MongoDB 初始化失败，已降级为无持久化模式；异常类型=%s",
            type(exc).__name__,
        )


class ProfessionalDataRequest(BaseModel):
    """用户显式开启专业增强时，只接受服务端签发的一次性主体 Token。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    enabled: bool = False
    resolution_token: str | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def require_token_when_enabled(self) -> "ProfessionalDataRequest":
        if self.enabled and not self.resolution_token:
            raise ValueError("启用专业数据时必须提交主体确认 Token")
        return self


class ResearchRequest(BaseModel):
    company: str
    company_url: str | None = None
    industry: str | None = None
    hq_location: str | None = None
    professional_data: ProfessionalDataRequest | None = None


class PDFGenerationRequest(BaseModel):
    report_content: str
    company_name: str | None = None


def _research_accepted_response(
    job_id: str,
    professional_data: dict[str, str | None] | None = None,
) -> dict[str, object]:
    """构造兼容旧客户端的受理响应，并按需附加专业分支状态。"""
    response: dict[str, object] = {
        "status": "accepted",
        "job_id": job_id,
        "message": (f"调研任务已启动,请连接 /research/{job_id}/stream 获取实时进度。"),
    }
    if professional_data is not None:
        response["professional_data"] = professional_data
    return response


def _register_background_task(task: asyncio.Task) -> None:
    """持有后台任务强引用，并在终态后从运行时集合移除。"""
    app.state.research_tasks.add(task)
    task.add_done_callback(app.state.research_tasks.discard)


@dataclass
class _ResearchTaskControl:
    started: bool = False


async def _run_scheduled_research(
    coroutine: Coroutine[Any, Any, None],
    control: _ResearchTaskControl,
) -> None:
    control.started = True
    await coroutine


def _schedule_research(
    coroutine: Coroutine[Any, Any, None],
    *,
    runtime: CompanyIntelligenceRuntime,
    preparation: ProfessionalPreparation | None,
) -> asyncio.Task:
    """托管调研任务；首次运行前取消时释放尚未执行的专业预留。"""
    control = _ResearchTaskControl()
    runner = _run_scheduled_research(coroutine, control)
    try:
        task = asyncio.create_task(runner)
    except BaseException:
        runner.close()
        coroutine.close()
        raise

    def cleanup_unstarted(done_task: asyncio.Task) -> None:
        if not control.started:
            coroutine.close()
            if preparation is not None:
                try:
                    runtime.abandon_professional_research(preparation)
                except Exception as exc:
                    logger.warning(
                        "未启动专业预留释放失败，异常类型=%s",
                        type(exc).__name__,
                    )
        app.state.research_tasks.discard(done_task)

    app.state.research_tasks.add(task)
    task.add_done_callback(cleanup_unstarted)
    return task


@app.post("/research")
async def research(data: ResearchRequest, request: Request):
    """受理基础调研；专业分支只在显式请求且原子准入成功后启动。"""
    try:
        prune_expired_jobs()
        logger.info(f"收到调研请求: {data.company}")
        job_id = str(uuid.uuid4())
        preparation: ProfessionalPreparation | None = None
        blocked_reason: str | None = None
        professional_response: dict[str, str | None] | None = None
        professional = data.professional_data
        runtime = request.app.state.company_intelligence
        scheduled = False

        if professional is not None and professional.enabled:
            peer_ip = request.client.host if request.client else "unknown"
            client_ip = resolve_client_ip(
                peer_ip=peer_ip,
                forwarded_for=request.headers.get("x-forwarded-for"),
                trusted_proxy_cidrs=runtime.settings.trusted_proxy_cidrs,
            )
            preparation = runtime.prepare_professional_research(
                job_id=job_id,
                resolution_token=professional.resolution_token or "",
                client_ip=client_ip,
            )
            if preparation.kind in {
                PreparationKind.IN_PROGRESS,
                PreparationKind.REPLAYED,
            }:
                replayed_job_id = preparation.job_id or job_id
                state = (
                    "in_progress"
                    if preparation.kind == PreparationKind.IN_PROGRESS
                    else "replayed"
                )
                return JSONResponse(
                    content=_research_accepted_response(
                        replayed_job_id,
                        {"status": state, "reason": None},
                    )
                )
            if preparation.kind == PreparationKind.BLOCKED:
                blocked_reason = preparation.reason_code or "provider_unavailable"
                professional_response = {
                    "status": "degraded",
                    "reason": blocked_reason,
                }
                preparation = None
            else:
                if preparation.identity is None or preparation.reservation_id is None:
                    runtime.abandon_professional_research(preparation)
                    blocked_reason = "provider_unavailable"
                    professional_response = {
                        "status": "degraded",
                        "reason": blocked_reason,
                    }
                    preparation = None
                else:
                    professional_response = {
                        "status": "accepted",
                        "reason": None,
                    }

        # Token 已在准入阶段消费；后台任务和 Mongo 只接收基础字段。
        sanitized_update = {"professional_data": None}
        if preparation is not None and preparation.identity is not None:
            # 专业 Evidence 与基础报告必须使用 Token 内同一规范主体，不能信任
            # 客户端在确认主体后再次提交的 company 文本。
            sanitized_update["company"] = preparation.identity.canonical_name
        sanitized_data = data.model_copy(update=sanitized_update)
        _schedule_research(
            process_research(
                job_id,
                sanitized_data,
                professional_preparation=preparation,
                professional_blocked_reason=blocked_reason,
            ),
            runtime=runtime,
            preparation=preparation,
        )
        scheduled = True

        return JSONResponse(
            content=_research_accepted_response(job_id, professional_response)
        )

    except Exception as exc:
        if (
            "scheduled" in locals()
            and not scheduled
            and "preparation" in locals()
            and preparation is not None
        ):
            try:
                runtime.abandon_professional_research(preparation)
            except Exception as abandon_error:
                logger.warning(
                    "专业数据启动失败终态写入失败，异常类型=%s",
                    type(abandon_error).__name__,
                )
        logger.error(
            "启动调研任务失败，异常类型=%s",
            type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail="启动调研任务失败") from exc


async def _collect_professional_for_job(
    job_id: str,
    preparation: ProfessionalPreparation,
    control: "_ProfessionalTaskControl",
) -> None:
    """采集专业证据并写入安全任务状态；失败不向基础 Graph 传播。"""
    control.started = True
    job_status[job_id]["events"].append({"type": "professional_data_started"})
    try:
        evidence = await app.state.company_intelligence.collect_professional_research(
            preparation
        )
    except BaseException as exc:
        current_task = asyncio.current_task()
        if (
            isinstance(exc, asyncio.CancelledError)
            and current_task is not None
            and current_task.cancelling()
        ):
            raise
        if not isinstance(exc, Exception) and not isinstance(
            exc, asyncio.CancelledError
        ):
            raise
        logger.warning(
            "专业数据分支降级，job_id=%s，异常类型=%s",
            job_id,
            type(exc).__name__,
        )
        if control.publish_results:
            job_status[job_id]["events"].append(
                {
                    "type": "professional_data_degraded",
                    "reason": "provider_unavailable",
                }
            )
        return

    if not control.publish_results:
        return
    job_status[job_id]["professional_evidence"] = evidence.model_dump(mode="json")
    job_status[job_id]["events"].append({"type": "professional_data_completed"})


@dataclass
class _ProfessionalTaskControl:
    started: bool = False
    publish_results: bool = True


def _schedule_professional_for_job(
    job_id: str,
    preparation: ProfessionalPreparation,
    control: _ProfessionalTaskControl,
) -> asyncio.Task[None]:
    """创建专业子任务；首次执行前取消时释放未 claim 的预算预留。"""
    runtime = app.state.company_intelligence
    coroutine = _collect_professional_for_job(job_id, preparation, control)
    try:
        task = asyncio.create_task(coroutine)
    except BaseException:
        coroutine.close()
        raise

    def cleanup_unstarted(done_task: asyncio.Task[None]) -> None:
        if control.started:
            return
        try:
            runtime.abandon_professional_research(preparation)
        except Exception as exc:
            logger.warning(
                "未启动专业子任务预留释放失败，异常类型=%s",
                type(exc).__name__,
            )

    task.add_done_callback(cleanup_unstarted)
    return task


async def _drain_professional_task(task: asyncio.Task[None]) -> None:
    """等待已脱离报告主链路的专业任务退出，并吞掉其内部终态异常。"""
    try:
        await task
    except BaseException:
        return


def _detach_professional_task(
    task: asyncio.Task[None],
    control: _ProfessionalTaskControl,
) -> None:
    """禁止晚到结果发布，取消任务并把无界清理移交后台。"""
    control.publish_results = False
    task.cancel()
    drain_task = asyncio.create_task(_drain_professional_task(task))
    _register_background_task(drain_task)


async def _await_professional_for_job(
    job_id: str,
    professional_task: asyncio.Task[None],
    control: _ProfessionalTaskControl,
) -> asyncio.Task[None] | None:
    """只等待固定窗口；超时清理脱离主链路，基础报告继续交付。"""
    done, _pending = await asyncio.wait(
        {professional_task},
        timeout=_PROFESSIONAL_COLLECTION_TIMEOUT_SECONDS,
    )
    if not done:
        logger.warning("专业数据分支超时，job_id=%s", job_id)
        _detach_professional_task(professional_task, control)
        job_status[job_id]["events"].append(
            {
                "type": "professional_data_degraded",
                "reason": "provider_unavailable",
            }
        )
        return None

    try:
        await professional_task
    except asyncio.CancelledError:
        current_task = asyncio.current_task()
        if current_task is not None and current_task.cancelling():
            raise
    except Exception as exc:
        logger.warning(
            "专业数据子任务异常，job_id=%s，异常类型=%s",
            job_id,
            type(exc).__name__,
        )
    else:
        return professional_task

    if control.publish_results:
        job_status[job_id]["events"].append(
            {
                "type": "professional_data_degraded",
                "reason": "provider_unavailable",
            }
        )
    return professional_task


def _append_professional_evidence(
    report_content: str,
    serialized_evidence: object,
) -> tuple[str, bool]:
    """追加专业附录，并保证最终 complete 事件留在持久化大小边界内。"""

    def complete_event_size(report: str) -> int:
        probe = {
            "type": "complete",
            "report": report,
            "version": 1,
            "event_id": 9_999_999_999,
        }
        return len(
            json.dumps(
                probe,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    def fit_with_notice(report: str, notice: str) -> str:
        """二分保留尽可能多的基础报告，同时确保终态事件可编码。"""
        suffix = f"\n\n{notice}"
        lower = 0
        upper = len(report)
        while lower < upper:
            middle = (lower + upper + 1) // 2
            candidate_prefix = report[:middle].rstrip()
            if (
                complete_event_size(f"{candidate_prefix}{suffix}")
                <= _MAX_FINAL_REPORT_EVENT_BYTES
            ):
                lower = middle
            else:
                upper = middle - 1
        return f"{report[:lower].rstrip()}{suffix}"

    evidence = ProfessionalEvidence.model_validate(serialized_evidence)
    appendix = render_professional_evidence_markdown(evidence)
    base_report = report_content.rstrip()
    candidate = f"{base_report}\n\n{appendix}"

    if complete_event_size(candidate) <= _MAX_FINAL_REPORT_EVENT_BYTES:
        return candidate, False

    size_notice = (
        "## 工商与司法专业数据\n\n"
        "> 专业数据已采集，但因最终报告大小限制未展开；基础 Web 报告不受影响。"
    )
    candidate = f"{base_report}\n\n{size_notice}"
    if complete_event_size(candidate) <= _MAX_FINAL_REPORT_EVENT_BYTES:
        return candidate, True
    delivery_notice = (
        "## 报告交付说明\n\n"
        "> 基础 Web 报告因超过交付大小限制已截断；专业数据已采集，但未在本报告中展开。"
    )
    return fit_with_notice(report_content, delivery_notice), True


async def process_research(
    job_id: str,
    data: ResearchRequest,
    *,
    professional_preparation: ProfessionalPreparation | None = None,
    professional_blocked_reason: str | None = None,
):
    """异步执行调研任务,把结果写入 job_status / MongoDB。"""
    professional_task: asyncio.Task[None] | None = None
    professional_started = False
    professional_control = _ProfessionalTaskControl()
    try:
        # 在 Graph 节点启动前建立事件日志，保证最早的流式事件也能入队。
        job_status[job_id]
        if mongodb:
            mongodb.create_job(
                job_id,
                data.model_dump(exclude={"professional_data"}),
            )

        if professional_blocked_reason:
            event_type = (
                "professional_data_budget_blocked"
                if professional_blocked_reason == "budget_blocked"
                else "professional_data_degraded"
            )
            job_status[job_id]["events"].append(
                {"type": event_type, "reason": professional_blocked_reason}
            )
        if professional_preparation is not None:
            professional_task = _schedule_professional_for_job(
                job_id,
                professional_preparation,
                professional_control,
            )
            professional_started = True

        await asyncio.sleep(0.5)  # 留一点时间让 SSE 客户端先连上来

        logger.info(f"开始调研: {data.company}")

        graph = Graph(
            company=data.company,
            url=data.company_url,
            industry=data.industry,
            hq_location=data.hq_location,
            job_id=job_id,
        )

        final_state = {}

        # 流式跑 graph,顺便更新进度
        async for state in graph.run(thread={}):
            final_state.update(state)
            node_name = list(state.keys())[0] if state else "unknown"
            logger.debug(f"节点已完成: {node_name}")

            # 把当前 step 写入 job 状态
            job_status[job_id].update(
                {
                    "status": "processing",
                    "current_step": node_name,
                    "last_update": datetime.now().isoformat(),
                }
            )
            job_status[job_id]["events"].append({"type": "progress", "step": node_name})

        # 取出最终报告
        report_content = final_state.get("report") or (
            final_state.get("editor") or {}
        ).get("report")

        if professional_task is not None:
            professional_task = await _await_professional_for_job(
                job_id,
                professional_task,
                professional_control,
            )

        serialized_evidence = job_status[job_id].get("professional_evidence")
        if report_content and serialized_evidence is not None:
            try:
                report_content, appendix_omitted = _append_professional_evidence(
                    report_content,
                    serialized_evidence,
                )
                if appendix_omitted:
                    job_status[job_id]["events"].append(
                        {
                            "type": "professional_data_degraded",
                            "reason": "report_size_limit",
                        }
                    )
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "专业证据渲染失败，job_id=%s，异常类型=%s",
                    job_id,
                    type(exc).__name__,
                )
                job_status[job_id]["events"].append(
                    {
                        "type": "professional_data_degraded",
                        "reason": "provider_unavailable",
                    }
                )

        if report_content:
            logger.info(f"调研完成,报告长度: {len(report_content)} 字符")

            if mongodb:
                mongodb.update_job(job_id=job_id, status="completed")
                mongodb.store_report(
                    job_id=job_id, report_data={"report": report_content}
                )

            job_status[job_id].update(
                {
                    "report": report_content,
                    "company": data.company,
                    "last_update": datetime.now().isoformat(),
                    "expires_at_epoch": time.time() + JOB_TERMINAL_TTL_SECONDS,
                }
            )
            job_status[job_id]["events"].append(
                {"type": "complete", "report": report_content}
            )
            job_status[job_id]["status"] = "completed"

            logger.info(f"{data.company} 调研流程已成功结束")
        else:
            logger.error(
                f"调研流程结束但未生成报告。state keys: {list(final_state.keys())}"
            )
            job_status[job_id].update(
                {
                    "error": "未生成报告内容",
                    "last_update": datetime.now().isoformat(),
                    "expires_at_epoch": time.time() + JOB_TERMINAL_TTL_SECONDS,
                }
            )
            job_status[job_id]["events"].append(
                {
                    "type": "error",
                    "error": "未生成报告内容",
                    "reason": "report_missing",
                }
            )
            job_status[job_id]["status"] = "failed"

    except Exception as e:
        logger.error(
            "调研失败，job_id=%s，异常类型=%s",
            job_id,
            type(e).__name__,
        )
        job_status[job_id].update(
            {
                "error": "调研任务执行失败",
                "last_update": datetime.now().isoformat(),
                "expires_at_epoch": time.time() + JOB_TERMINAL_TTL_SECONDS,
            }
        )
        job_status[job_id]["events"].append(
            {
                "type": "error",
                "error": "调研任务执行失败",
                "reason": "research_failed",
            }
        )
        job_status[job_id]["status"] = "failed"

        if professional_preparation is not None and not professional_started:
            try:
                app.state.company_intelligence.abandon_professional_research(
                    professional_preparation
                )
            except Exception as abandon_error:
                logger.warning(
                    "专业数据未启动终态写入失败，异常类型=%s",
                    type(abandon_error).__name__,
                )
        if mongodb:
            mongodb.update_job(
                job_id=job_id,
                status="failed",
                error="调研任务执行失败",
            )
    finally:
        if professional_task is not None and not professional_task.done():
            _detach_professional_task(
                professional_task,
                professional_control,
            )


@app.get("/")
async def ping():
    return {"status": "ok", "message": "服务正常"}


@app.get("/research/pdf/{filename}")
async def get_pdf(filename: str):
    pdf_path = os.path.join("pdfs", filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF 文件不存在")
    return FileResponse(pdf_path, media_type="application/pdf", filename=filename)


@app.get("/research/{job_id}")
async def get_research(job_id: str):
    if not mongodb:
        raise HTTPException(
            status_code=501, detail="未配置数据库持久化,无法查询历史任务"
        )
    job = mongodb.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到对应的调研任务")
    return job


@app.get("/research/{job_id}/stream")
async def stream_research(job_id: str, request: Request):
    """按每个连接自己的 Last-Event-ID 推送和重放任务事件。"""
    prune_expired_jobs()
    raw_last_event_id = request.headers.get("last-event-id", "0")
    try:
        initial_event_id = int(raw_last_event_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Last-Event-ID 必须是非负整数")
    if initial_event_id < 0:
        raise HTTPException(status_code=400, detail="Last-Event-ID 必须是非负整数")

    async def event_generator():
        try:
            # 等待 job 入库(最多 5s)
            for _ in range(50):
                if job_id in job_status:
                    break
                await asyncio.sleep(0.1)

            last_event_id = initial_event_id

            # 每个连接只推进自己的游标，不修改共享事件日志。
            while job_id in job_status:
                result = job_status[job_id]
                status = result.get("status")
                events = result.get("events", [])

                if not isinstance(events, JobEventLog):
                    normalized_events = JobEventLog()
                    normalized_events.extend(events)
                    result["events"] = normalized_events
                    events = normalized_events

                if events.history_expired(last_event_id):
                    data = json.dumps(
                        {
                            "type": "stream_reset_required",
                            "reason": "event_history_expired",
                            "version": 1,
                        },
                        ensure_ascii=False,
                    )
                    yield f"data: {data}\n\n"
                    break

                pending_events = events.after(last_event_id)
                for event in pending_events:
                    data = json.dumps(event, ensure_ascii=False)
                    event_id = int(event["event_id"])
                    yield f"id: {event_id}\ndata: {data}\n\n"
                    last_event_id = event_id

                if status in {"completed", "failed"}:
                    break

                await asyncio.sleep(0.1)  # 加快轮询,前端反馈更跟手
        except Exception as e:
            logger.warning(
                "SSE 推送失败，job_id=%s，异常类型=%s",
                job_id,
                type(e).__name__,
            )
            data = json.dumps(
                {
                    "type": "stream_error",
                    "reason": "stream_failed",
                    "version": 1,
                },
                ensure_ascii=False,
            )
            yield f"data: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/research/{job_id}/report")
async def get_research_report(job_id: str):
    prune_expired_jobs()
    if not mongodb:
        if job_id in job_status:
            result = job_status[job_id]
            if report := result.get("report"):
                return {"report": report}
            # 任务存在但报告还没生成完
            return JSONResponse(
                status_code=202,
                content={
                    "status": result.get("status", "pending"),
                    "message": "报告尚未生成完成",
                },
            )
        raise HTTPException(status_code=404, detail="未找到对应的调研任务")

    report = mongodb.get_report(job_id)
    if not report:
        # 检查任务本身是否存在
        if job := mongodb.get_job(job_id):
            return JSONResponse(
                status_code=202,
                content={
                    "status": job.get("status", "pending"),
                    "message": "报告尚未生成完成",
                },
            )
        raise HTTPException(status_code=404, detail="未找到对应的调研任务")
    return report


@app.post("/generate-pdf")
async def generate_pdf(data: PDFGenerationRequest):
    """根据 markdown 报告内容生成 PDF 并以流的方式返回。"""
    try:
        success, result = pdf_service.generate_pdf_stream(
            data.report_content, data.company_name
        )
        if success:
            pdf_buffer, filename = result
            return StreamingResponse(
                pdf_buffer,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        else:
            raise HTTPException(status_code=500, detail=f"PDF 生成失败: {result}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 生成失败: {str(e)}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
