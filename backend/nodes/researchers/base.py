import asyncio
import logging
from datetime import datetime
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from ...classes import ResearchState
from ...classes.state import job_status
from ...prompts import QUERY_FORMAT_GUIDELINES
from ...services.llm_factory import get_llm
from ...services.search import SearchProvider, SearchResult, get_search_provider
from ...utils.references import clean_title

logger = logging.getLogger(__name__)


class BaseResearcher:
    def __init__(
        self,
        *,
        search: SearchProvider | None = None,
        llm: Runnable[Any, Any] | None = None,
    ) -> None:
        # 检索通过统一 SearchProvider 调用,默认 Tavily;
        # API key 校验由 provider 内部完成,缺失时会抛 RuntimeError。
        self.search = search if search is not None else get_search_provider()
        # LLM 通过统一工厂获取，Zen 免费线路优先，失败时按服务端配置回退。
        # 模型可通过 LLM_MODEL_RESEARCHER 环境变量覆盖。
        self.llm = llm if llm is not None else get_llm("researcher")
        self.analyst_type = "base_researcher"

    @property
    def analyst_type(self) -> str:
        if not hasattr(self, "_analyst_type"):
            raise ValueError("子类未设置分析器类型")
        return self._analyst_type

    @analyst_type.setter
    def analyst_type(self, value: str):
        self._analyst_type = value

    async def generate_queries(self, state: dict, prompt: str):
        """生成搜索词，并在生成过程中持续产出事件。"""
        company = state.get("company", "未知公司")
        industry = state.get("industry", "未知行业")
        hq_location = state.get("hq_location", "未知地点")
        current_year = datetime.now().year
        job_id = state.get("job_id")

        logger.info(
            "=== 开始生成查询词：job_id=%s，analyst=%s ===",
            job_id,
            self.analyst_type,
        )
        if not job_id:
            logger.warning("⚠️ 状态中缺少 job_id，现有字段：%s", list(state.keys()))

        try:
            logger.info(
                "正在为 %s 生成 %s 查询词，job_id=%s",
                company,
                self.analyst_type,
                job_id,
            )

            # 使用 LangChain 创建提示模板
            query_prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You are researching {company}, a company in the {industry} industry, headquartered in {hq_location}.",
                    ),
                    (
                        "user",
                        """Researching {company} in {year}, as of {date}.
{task_prompt}
{format_guidelines}""",
                    ),
                ]
            )

            # 创建 LCEL 链
            chain = query_prompt | self.llm

            queries = []
            current_query = ""
            current_query_number = 1

            # 使用 LangChain 的 astream 流式生成查询词
            async for chunk in chain.astream(
                {
                    "company": company,
                    "industry": industry,
                    "hq_location": hq_location,
                    "year": current_year,
                    "date": datetime.now().strftime("%B %d, %Y"),
                    "task_prompt": prompt,
                    "format_guidelines": QUERY_FORMAT_GUIDELINES.format(
                        company=company
                    ),
                }
            ):
                current_query += chunk.content

                # 产出查询词生成进度
                event = {
                    "type": "query_generating",
                    "query": current_query,
                    "query_number": current_query_number,
                    "category": self.analyst_type,
                }

                # 累计 query 每个 token 都变长，只向调用链 yield，不写重放日志，
                # 避免 append-only SSE 形成 O(n²) 内存；完成的 query 仍会持久事件化。
                yield event

                # 按换行符解析已完成的查询词
                if "\n" in current_query:
                    parts = current_query.split("\n")
                    current_query = parts[-1]

                    for query in parts[:-1]:
                        query = query.strip()
                        if query:
                            queries.append(query)
                            event = {
                                "type": "query_generated",
                                "query": query,
                                "query_number": len(queries),
                                "category": self.analyst_type,
                            }

                            # 提供 job_id 时同步任务状态
                            if job_id:
                                try:
                                    if job_id in job_status:
                                        job_status[job_id]["events"].append(event)
                                    else:
                                        logger.warning(
                                            "追加 query_generated 事件时未找到 job_id=%s",
                                            job_id,
                                        )
                                except Exception as exc:
                                    logger.error(
                                        "追加 query_generated 事件失败，异常类型=%s",
                                        type(exc).__name__,
                                    )

                            yield event
                            current_query_number += 1

            # 加入最后一条尚未换行的查询词
            if current_query.strip():
                queries.append(current_query.strip())
                yield {
                    "type": "query_generated",
                    "query": current_query.strip(),
                    "query_number": len(queries),
                    "category": self.analyst_type,
                }

            if not queries:
                raise ValueError(f"未能为 {company} 生成查询词")

            queries = queries[:4]  # 最多保留 4 条查询词
            logger.info("%s 的最终查询词：%s", self.analyst_type, queries)

            yield {
                "type": "queries_complete",
                "queries": queries,
                "count": len(queries),
            }

        except Exception as e:
            logger.error(
                "生成查询词失败，异常类型=%s",
                type(e).__name__,
            )
            raise RuntimeError("严重 API 错误：查询词生成失败") from None

    def _get_search_params(self) -> dict[str, Any]:
        """根据分析器类型生成搜索参数。

        ``max_results`` 是 ``SearchProvider.search`` 的显式参数,其余字段
        (``search_depth``、``include_raw_content``、``topic``)是 Tavily
        专有参数,通过 provider 的 ``**kwargs`` 透传;未来切换到其他
        provider 时,可在该方法里基于 ``self.analyst_type`` 输出对应的
        参数集合。
        """
        params = {
            "search_depth": "basic",
            "include_raw_content": False,
            "max_results": 5,
        }

        topic_map = {"news_analyzer": "news", "financial_analyzer": "finance"}

        if topic := topic_map.get(self.analyst_type):
            params["topic"] = topic

        return params

    def _process_search_result(
        self, result: SearchResult, query: str
    ) -> dict[str, Any]:
        """把单条 ``SearchResult`` 标准化为下游节点期望的 dict 形态。"""
        if not result.content or not result.url:
            return {}

        url = result.url
        title = clean_title(result.title) if result.title else ""

        # 重置空标题或无效标题
        if not title or title.lower() == url.lower():
            title = ""

        return {
            "title": title,
            "content": result.content,
            "query": query,
            "url": url,
            "source": "web_search",
            "score": result.score,
        }

    async def search_documents(self, state: ResearchState, queries: list[str]):
        """通过 SearchProvider 并行执行所有查询并 yield 进度事件。"""
        if not queries:
            logger.error("没有可执行的有效查询词")
            yield {
                "type": "research_degraded",
                "reason": "no_valid_queries",
            }
            return

        # 产出搜索开始事件
        yield {
            "type": "search_started",
            "message": f"正在执行 {len(queries)} 条查询",
            "total_queries": len(queries),
        }

        # 通过数据提供方抽象并行执行全部搜索
        search_params = self._get_search_params()
        search_tasks = [self.search.search(query, **search_params) for query in queries]

        try:
            results = await asyncio.gather(*search_tasks, return_exceptions=True)
        except Exception as e:
            logger.error(
                "并行搜索执行失败，异常类型=%s",
                type(e).__name__,
            )
            yield {"type": "research_degraded", "reason": "search_failed"}
            return

        # 处理并合并搜索结果
        merged_docs: dict[str, dict[str, Any]] = {}
        for query, result in zip(queries, results, strict=True):
            if isinstance(result, Exception):
                logger.error(
                    "查询执行失败，异常类型=%s",
                    type(result).__name__,
                )
                yield {
                    "type": "query_error",
                    "query": query,
                    "reason": "search_failed",
                }
                continue

            # provider 直接返回 list[SearchResult]
            for item in result:
                if doc := self._process_search_result(item, query):
                    merged_docs[doc["url"]] = doc

        # 产出搜索完成事件
        yield {
            "type": "search_complete",
            "message": f"已发现 {len(merged_docs)} 份文档",
            "total_documents": len(merged_docs),
            "queries_processed": len(queries),
            "merged_docs": merged_docs,
        }
