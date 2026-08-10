import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate

from ...classes import ResearchState
from ...classes.state import job_status
from ...prompts import QUERY_FORMAT_GUIDELINES
from ...services.llm_factory import get_llm
from ...services.search import SearchResult, get_search_provider
from ...utils.references import clean_title

logger = logging.getLogger(__name__)


class BaseResearcher:
    def __init__(self):
        # 检索通过统一 SearchProvider 调用,默认 Tavily;
        # API key 校验由 provider 内部完成,缺失时会抛 RuntimeError。
        self.search = get_search_provider()
        # LLM 通过统一工厂获取,默认走 OpenRouter,降级 OpenAI;
        # 模型可通过 LLM_MODEL_RESEARCHER 环境变量覆盖。
        self.llm = get_llm("researcher")
        self.analyst_type = "base_researcher"

    @property
    def analyst_type(self) -> str:
        if not hasattr(self, "_analyst_type"):
            raise ValueError("子类未设置分析器类型")
        return self._analyst_type

    @analyst_type.setter
    def analyst_type(self, value: str):
        self._analyst_type = value

    async def generate_queries(self, state: Dict, prompt: str):
        """Generate search queries and yield events as they're created"""
        company = state.get("company", "Unknown Company")
        industry = state.get("industry", "Unknown Industry")
        hq_location = state.get("hq_location", "Unknown")
        current_year = datetime.now().year
        job_id = state.get("job_id")

        logger.info(
            f"=== GENERATE_QUERIES START: job_id={job_id}, analyst={self.analyst_type} ==="
        )
        if not job_id:
            logger.warning(f"⚠️ NO JOB_ID in state! Keys: {list(state.keys())}")

        try:
            logger.info(
                f"Generating queries for {company} as {self.analyst_type}, job_id={job_id}"
            )

            # Create prompt template using LangChain
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

            # Create LCEL chain
            chain = query_prompt | self.llm

            queries = []
            current_query = ""
            current_query_number = 1

            # Stream queries using LangChain's astream
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

                # Yield query generation progress
                event = {
                    "type": "query_generating",
                    "query": current_query,
                    "query_number": current_query_number,
                    "category": self.analyst_type,
                }

                # 累计 query 每个 token 都变长，只向调用链 yield，不写重放日志，
                # 避免 append-only SSE 形成 O(n²) 内存；完成的 query 仍会持久事件化。
                yield event

                # Parse completed queries on newline
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

                            # Update job status if job_id provided
                            if job_id:
                                try:
                                    if job_id in job_status:
                                        job_status[job_id]["events"].append(event)
                                    else:
                                        logger.warning(
                                            f"job_id {job_id} not found in job_status for query_generated"
                                        )
                                except Exception as e:
                                    logger.error(
                                        f"Error appending query_generated event: {e}"
                                    )

                            yield event
                            current_query_number += 1

            # Add remaining query
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

            queries = queries[:4]  # Limit to 4 queries
            logger.info(f"Final queries for {self.analyst_type}: {queries}")

            yield {
                "type": "queries_complete",
                "queries": queries,
                "count": len(queries),
            }

        except Exception as e:
            logger.error(
                "Error generating queries, exception_type=%s",
                type(e).__name__,
            )
            raise RuntimeError("严重 API 错误：查询词生成失败") from None

    def _get_search_params(self) -> Dict[str, Any]:
        """Get search parameters based on analyst type.

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
    ) -> Dict[str, Any]:
        """把单条 ``SearchResult`` 标准化为下游节点期望的 dict 形态。"""
        if not result.content or not result.url:
            return {}

        url = result.url
        title = clean_title(result.title) if result.title else ""

        # Reset empty or invalid titles
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

    async def search_documents(self, state: ResearchState, queries: List[str]):
        """通过 SearchProvider 并行执行所有查询并 yield 进度事件。"""
        if not queries:
            logger.error("No valid queries to search")
            yield {
                "type": "research_degraded",
                "reason": "no_valid_queries",
            }
            return

        # Yield start event
        yield {
            "type": "search_started",
            "message": f"Searching {len(queries)} queries",
            "total_queries": len(queries),
        }

        # Execute all searches in parallel through the provider abstraction
        search_params = self._get_search_params()
        search_tasks = [self.search.search(query, **search_params) for query in queries]

        try:
            results = await asyncio.gather(*search_tasks, return_exceptions=True)
        except Exception as e:
            logger.error(
                "Error during parallel search execution, exception_type=%s",
                type(e).__name__,
            )
            yield {"type": "research_degraded", "reason": "search_failed"}
            return

        # Process and merge results
        merged_docs: Dict[str, Dict[str, Any]] = {}
        for query, result in zip(queries, results, strict=True):
            if isinstance(result, Exception):
                logger.error(
                    "Search failed for query, exception_type=%s",
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

        # Yield completion event
        yield {
            "type": "search_complete",
            "message": f"Found {len(merged_docs)} documents",
            "total_documents": len(merged_docs),
            "queries_processed": len(queries),
            "merged_docs": merged_docs,
        }
