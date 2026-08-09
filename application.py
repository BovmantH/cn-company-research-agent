import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.graph import Graph
from backend.services.mongodb import MongoDBService
from backend.services.pdf_service import PDFService
from backend.services.company_intelligence.runtime import CompanyIntelligenceRuntime
from backend.classes.state import job_status

# Load environment variables from .env file at startup
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)

# 启动校验: LLMFactory 依赖至少一个 LLM provider key,缺失则直接退出,
# 避免在第一次请求时才发现 key 没配,把错误推到用户面前。
_LLM_KEY_CANDIDATES = (
    ("DEEPSEEK_API_KEY",   "DeepSeek 原厂",       "https://api-docs.deepseek.com/"),
    ("DASHSCOPE_API_KEY",  "阿里百炼(Qwen)",     "https://help.aliyun.com/zh/dashscope/"),
    ("MOONSHOT_API_KEY",   "Moonshot(Kimi)",     "https://platform.moonshot.cn/"),
    ("XIAOMI_API_KEY",     "小米 MiMo",          "https://api.xiaomimimo.com/"),
    ("OPENROUTER_API_KEY", "OpenRouter 聚合",     "https://openrouter.ai/"),
    ("OPENAI_API_KEY",     "OpenAI 原生(降级)", "https://platform.openai.com/"),
)
if not any(os.getenv(name) for name, _, _ in _LLM_KEY_CANDIDATES):
    # 把 stderr 切到 UTF-8,避免 Windows GBK 控制台把中文打成 mojibake
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    candidates = "\n".join(
        f"  - {name:<22}({label},见 {url})"
        for name, label, url in _LLM_KEY_CANDIDATES
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(app.state.company_intelligence.settings.allowed_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
pdf_service = PDFService({"pdf_output_dir": "pdfs"})


@app.get("/capabilities")
async def get_capabilities(request: Request):
    """返回可安全公开的部署能力，不泄露密钥、余额或上游错误。"""
    runtime: CompanyIntelligenceRuntime = request.app.state.company_intelligence
    return {"professional_company_data": runtime.capability_state().as_dict()}


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
        logger.info("已启用 MongoDB 持久化")
    except Exception as e:
        logger.warning(f"MongoDB 初始化失败: {e}。已降级为无持久化模式继续运行。")

class ResearchRequest(BaseModel):
    company: str
    company_url: str | None = None
    industry: str | None = None
    hq_location: str | None = None

class PDFGenerationRequest(BaseModel):
    report_content: str
    company_name: str | None = None

@app.post("/research")
async def research(data: ResearchRequest):
    try:
        logger.info(f"收到调研请求: {data.company}")
        job_id = str(uuid.uuid4())
        asyncio.create_task(process_research(job_id, data))

        return JSONResponse(content={
            "status": "accepted",
            "job_id": job_id,
            "message": "调研任务已启动,请连接 /research/{job_id}/stream 获取实时进度。"
        })

    except Exception as e:
        logger.error(f"启动调研任务失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动调研任务失败: {str(e)}")

async def process_research(job_id: str, data: ResearchRequest):
    """异步执行调研任务,把结果写入 job_status / MongoDB。"""
    try:
        if mongodb:
            mongodb.create_job(job_id, data.dict())

        await asyncio.sleep(0.5)  # 留一点时间让 SSE 客户端先连上来

        logger.info(f"开始调研: {data.company}")

        graph = Graph(
            company=data.company,
            url=data.company_url,
            industry=data.industry,
            hq_location=data.hq_location,
            job_id=job_id
        )

        final_state = {}

        # 流式跑 graph,顺便更新进度
        async for state in graph.run(thread={}):
            final_state.update(state)
            node_name = list(state.keys())[0] if state else 'unknown'
            logger.debug(f"节点已完成: {node_name}")

            # 把当前 step 写入 job 状态
            job_status[job_id].update({
                "status": "processing",
                "current_step": node_name,
                "last_update": datetime.now().isoformat()
            })

        # 取出最终报告
        report_content = final_state.get('report') or (final_state.get('editor') or {}).get('report')

        if report_content:
            logger.info(f"调研完成,报告长度: {len(report_content)} 字符")

            job_status[job_id].update({
                "status": "completed",
                "report": report_content,
                "company": data.company,
                "last_update": datetime.now().isoformat()
            })

            if mongodb:
                mongodb.update_job(job_id=job_id, status="completed")
                mongodb.store_report(job_id=job_id, report_data={"report": report_content})

            logger.info(f"{data.company} 调研流程已成功结束")
        else:
            logger.error(f"调研流程结束但未生成报告。state keys: {list(final_state.keys())}")
            job_status[job_id].update({
                "status": "failed",
                "error": "未生成报告内容",
                "last_update": datetime.now().isoformat()
            })

    except Exception as e:
        logger.error(f"调研失败: {str(e)}", exc_info=True)
        job_status[job_id].update({
            "status": "failed",
            "error": str(e),
            "last_update": datetime.now().isoformat()
        })

        if mongodb:
            mongodb.update_job(job_id=job_id, status="failed", error=str(e))

@app.get("/")
async def ping():
    return {"status": "ok", "message": "服务正常"}

@app.get("/research/pdf/{filename}")
async def get_pdf(filename: str):
    pdf_path = os.path.join("pdfs", filename)
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF 文件不存在")
    return FileResponse(pdf_path, media_type='application/pdf', filename=filename)

@app.get("/research/{job_id}")
async def get_research(job_id: str):
    if not mongodb:
        raise HTTPException(status_code=501, detail="未配置数据库持久化,无法查询历史任务")
    job = mongodb.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到对应的调研任务")
    return job

@app.get("/research/{job_id}/stream")
async def stream_research(job_id: str):
    """通过 SSE 推送调研进度。"""
    async def event_generator():
        try:
            # 等待 job 入库(最多 5s)
            for _ in range(50):
                if job_id in job_status:
                    break
                await asyncio.sleep(0.1)

            last_step = None

            # 持续推送状态更新
            while job_id in job_status:
                result = job_status[job_id]
                status = result.get("status")
                current_step = result.get("current_step")
                events = result.get("events", [])

                # step 切换时推一条 progress 事件
                if status == "processing" and current_step and current_step != last_step:
                    data = json.dumps({"type": "progress", "step": current_step}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                    last_step = current_step

                # 把队列里的事件按 FIFO 顺序推完
                while events:
                    event = events.pop(0)
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"data: {data}\n\n"

                if status == "completed" and (report := result.get("report")):
                    data = json.dumps({"type": "complete", "report": report}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                    break
                elif status == "failed":
                    data = json.dumps({"type": "error", "error": result.get("error", "未知错误")}, ensure_ascii=False)
                    yield f"data: {data}\n\n"
                    break

                await asyncio.sleep(0.1)  # 加快轮询,前端反馈更跟手
        except Exception as e:
            data = json.dumps({"type": "error", "error": str(e)}, ensure_ascii=False)
            yield f"data: {data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/research/{job_id}/report")
async def get_research_report(job_id: str):
    if not mongodb:
        if job_id in job_status:
            result = job_status[job_id]
            if report := result.get("report"):
                return {"report": report}
            # 任务存在但报告还没生成完
            return JSONResponse(
                status_code=202,
                content={"status": result.get("status", "pending"), "message": "报告尚未生成完成"}
            )
        raise HTTPException(status_code=404, detail="未找到对应的调研任务")

    report = mongodb.get_report(job_id)
    if not report:
        # 检查任务本身是否存在
        if job := mongodb.get_job(job_id):
            return JSONResponse(
                status_code=202,
                content={"status": job.get("status", "pending"), "message": "报告尚未生成完成"}
            )
        raise HTTPException(status_code=404, detail="未找到对应的调研任务")
    return report

@app.post("/generate-pdf")
async def generate_pdf(data: PDFGenerationRequest):
    """根据 markdown 报告内容生成 PDF 并以流的方式返回。"""
    try:
        success, result = pdf_service.generate_pdf_stream(data.report_content, data.company_name)
        if success:
            pdf_buffer, filename = result
            return StreamingResponse(
                pdf_buffer,
                media_type='application/pdf',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"'
                }
            )
        else:
            raise HTTPException(status_code=500, detail=f"PDF 生成失败: {result}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 生成失败: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
