import asyncio
import logging
from typing import Any, Dict, List, Union

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ..classes import ResearchState
from ..classes.state import job_status
from ..prompts import (
    BRIEFING_ANALYSIS_INSTRUCTION,
    COMPANY_BRIEFING_PROMPT,
    FINANCIAL_BRIEFING_PROMPT,
    INDUSTRY_BRIEFING_PROMPT,
    NEWS_BRIEFING_PROMPT,
)
from ..services.llm_factory import get_llm

logger = logging.getLogger(__name__)


class Briefing:
    """为每个调研类别生成简报并更新 ResearchState。"""

    def __init__(self) -> None:
        self.max_doc_length = 8000  # 单份文档正文的最大长度
        # LLM 通过统一工厂获取,默认走 OpenRouter,降级 OpenAI;
        # 模型可通过 LLM_MODEL_BRIEFING 环境变量覆盖(默认 qwen/qwen-2.5-72b-instruct)。
        # 简报阶段不需要流式输出,关掉以减少与上游的连接开销。
        self.llm = get_llm("briefing", streaming=False)

    def _get_category_prompt(self, category: str) -> str:
        """获取指定类别的提示模板。"""
        prompts = {
            "company": COMPANY_BRIEFING_PROMPT,
            "industry": INDUSTRY_BRIEFING_PROMPT,
            "financial": FINANCIAL_BRIEFING_PROMPT,
            "news": NEWS_BRIEFING_PROMPT,
        }
        return prompts.get(
            category,
            "Create a focused, informative and insightful research briefing on the company: {company} in the {industry} industry based on the provided documents.",
        )

    def _prepare_documents(
        self, docs: Union[Dict[str, Any], List[Dict[str, Any]]]
    ) -> str:
        """为生成简报准备并格式化文档。"""
        # 将文档规范化为 (url, doc) 元组列表
        items = (
            list(docs.items())
            if isinstance(docs, dict)
            else [(doc.get("url", f"doc_{i}"), doc) for i, doc in enumerate(docs)]
        )

        # 按评估分数排序
        sorted_items = sorted(
            items,
            key=lambda x: float(x[1].get("evaluation", {}).get("overall_score", "0")),
            reverse=True,
        )

        # 在长度限制内格式化文档
        doc_texts = []
        total_length = 0
        for _, doc in sorted_items:
            title = doc.get("title", "")
            content = doc.get("raw_content") or doc.get("content", "")

            if len(content) > self.max_doc_length:
                content = content[: self.max_doc_length] + "……[正文已截断]"

            doc_entry = f"Title: {title}\n\nContent: {content}"
            if total_length + len(doc_entry) < 120000:  # 保持在总长度限制内
                doc_texts.append(doc_entry)
                total_length += len(doc_entry)
            else:
                break

        separator = "\n" + "-" * 40 + "\n"
        return f"{separator}{separator.join(doc_texts)}{separator}"

    async def generate_category_briefing(
        self,
        docs: Union[Dict[str, Any], List[Dict[str, Any]]],
        category: str,
        context: Dict[str, Any],
    ):
        """生成类别简报并持续产出事件。"""
        company = context.get("company", "未知公司")
        industry = context.get("industry", "未知行业")
        hq_location = context.get("hq_location", "未知地点")
        job_id = context.get("job_id")

        logger.info(
            "正在使用 %s 份文档为 %s 生成 %s 简报",
            len(docs),
            company,
            category,
        )

        # 发送简报生成开始事件
        event = {
            "type": "briefing_start",
            "category": category,
            "total_docs": len(docs),
            "step": "生成简报",
        }

        if job_id:
            try:
                if job_id in job_status:
                    job_status[job_id]["events"].append(event)
            except Exception as exc:
                logger.error(
                    "追加 briefing_start 事件失败，异常类型=%s",
                    type(exc).__name__,
                )

        yield event

        # 获取类别提示模板并准备文档
        category_prompt = self._get_category_prompt(category).format(
            company=company, industry=industry, hq_location=hq_location
        )
        formatted_docs = self._prepare_documents(docs)

        # 创建用于生成简报的 LCEL 链
        briefing_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "user",
                    """{category_prompt}

{instruction}

{documents}""",
                )
            ]
        )

        chain = briefing_prompt | self.llm | StrOutputParser()

        try:
            logger.info("正在向 LLM 发送提示")
            content = await chain.ainvoke(
                {
                    "category_prompt": category_prompt,
                    "instruction": BRIEFING_ANALYSIS_INSTRUCTION,
                    "documents": formatted_docs,
                }
            )

            if not content:
                logger.error("LLM 返回的 %s 简报为空", category)
                yield {
                    "type": "briefing_degraded",
                    "reason": "empty_response",
                    "category": category,
                }
                yield {"content": ""}
                return

            # 发送简报生成完成事件
            event = {
                "type": "briefing_complete",
                "category": category,
                "content_length": len(content),
                "step": "生成简报",
            }

            if job_id:
                try:
                    if job_id in job_status:
                        job_status[job_id]["events"].append(event)
                except Exception as exc:
                    logger.error(
                        "追加 briefing_complete 事件失败，异常类型=%s",
                        type(exc).__name__,
                    )

            yield event
            yield {"content": content.strip()}
        except Exception as e:
            logger.error(
                "生成 %s 简报失败，异常类型=%s",
                category,
                type(e).__name__,
            )
            raise RuntimeError(f"严重 API 错误：{category} 简报生成失败") from None

    async def create_briefings(self, state: ResearchState) -> ResearchState:
        """并行为全部类别生成简报。"""
        company = state.get("company", "未知公司")
        logger.info("正在为 %s 生成各章节简报", company)

        context = {
            "company": company,
            "industry": state.get("industry", "未知行业"),
            "hq_location": state.get("hq_location", "未知地点"),
            "job_id": state.get("job_id"),
        }

        # 筛选数据字段与简报类别的映射
        categories = {
            "financial_data": ("financial", "financial_briefing"),
            "news_data": ("news", "news_briefing"),
            "industry_data": ("industry", "industry_briefing"),
            "company_data": ("company", "company_briefing"),
        }

        briefings = {}

        # 创建并行处理任务
        briefing_tasks = []
        for data_field, (cat, briefing_key) in categories.items():
            curated_key = f"curated_{data_field}"
            curated_data = state.get(curated_key, {})

            if curated_data:
                logger.info(
                    "正在处理 %s，共 %s 份文档",
                    data_field,
                    len(curated_data),
                )
                briefing_tasks.append(
                    {
                        "category": cat,
                        "briefing_key": briefing_key,
                        "data_field": data_field,
                        "curated_data": curated_data,
                    }
                )
            else:
                logger.info("%s 没有可用数据", data_field)
                state[briefing_key] = ""

        # 在限流约束下并行生成简报
        if briefing_tasks:
            briefing_semaphore = asyncio.Semaphore(2)  # 最多并发生成 2 份简报

            async def process_briefing(task: Dict[str, Any]) -> Dict[str, Any]:
                """在限流约束下生成单份简报。"""
                async with briefing_semaphore:
                    result = {"content": ""}

                    # 消费简报生成事件
                    # 异常不在这里捕获，直接向上传播
                    async for event in self.generate_category_briefing(
                        task["curated_data"], task["category"], context
                    ):
                        if isinstance(event, dict) and "content" in event:
                            result = event

                    if result["content"]:
                        briefings[task["category"]] = result["content"]
                        state[task["briefing_key"]] = result["content"]
                        logger.info(
                            "已完成 %s 简报，共 %s 个字符",
                            task["data_field"],
                            len(result["content"]),
                        )
                    else:
                        raise RuntimeError(f"为 {task['data_field']} 生成的简报为空")

                    return {
                        "category": task["category"],
                        "success": bool(result["content"]),
                        "length": len(result["content"]) if result["content"] else 0,
                    }

            # 并行处理全部简报；任一异常都会向上传播并终止流程
            results = await asyncio.gather(
                *[process_briefing(task) for task in briefing_tasks]
            )

            # 记录完成统计
            successful_briefings = sum(1 for r in results if r["success"])
            total_length = sum(r["length"] for r in results)
            logger.info(
                "已生成 %s/%s 份简报，总长度=%s",
                successful_briefings,
                len(briefing_tasks),
                total_length,
            )

        state["briefings"] = briefings
        return state

    async def run(self, state: ResearchState) -> ResearchState:
        return await self.create_briefings(state)
