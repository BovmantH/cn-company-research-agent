from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from ...classes import ResearchState
from ...prompts import INDUSTRY_ANALYZER_QUERY_PROMPT
from ...services.search import SearchProvider
from .base import BaseResearcher


class IndustryAnalyzer(BaseResearcher):
    def __init__(
        self,
        *,
        search: SearchProvider | None = None,
        llm: Runnable[Any, Any] | None = None,
    ) -> None:
        super().__init__(search=search, llm=llm)
        self.analyst_type = "industry_analyzer"

    async def analyze(self, state: ResearchState):
        """分析行业信息并持续产出事件。"""
        company = state.get("company", "未知公司")
        industry = state.get("industry", "未知行业")

        # 生成搜索词并持续产出事件
        queries = []
        async for event in self.generate_queries(state, INDUSTRY_ANALYZER_QUERY_PROMPT):
            yield event
            if event.get("type") == "queries_complete":
                queries = event.get("queries", [])

        # 记录行业分析子查询
        subqueries_msg = "🔍 行业分析子查询：\n" + "\n".join(
            [f"• {query}" for query in queries]
        )
        state.setdefault("messages", []).append(AIMessage(content=subqueries_msg))

        # 以站点抓取数据作为初始内容
        industry_data = dict(state.get("site_scrape", {}))

        # 搜索并合并文档，同时持续产出事件
        documents = {}
        async for event in self.search_documents(state, queries):
            yield event
            if event.get("type") == "search_complete":
                documents = event.get("merged_docs", {})

        industry_data.update(documents)

        # 更新状态
        completion_msg = (
            f"🏭 行业分析器为 {company} 在 {industry} 中找到 "
            f"{len(industry_data)} 份文档"
        )
        state.setdefault("messages", []).append(AIMessage(content=completion_msg))
        state["industry_data"] = industry_data

        yield {
            "type": "analysis_complete",
            "data_type": "industry_data",
            "count": len(industry_data),
        }
        yield {"message": [completion_msg], "industry_data": industry_data}

    async def run(self, state: ResearchState):
        """执行分析并产出全部事件。"""
        result = None
        async for event in self.analyze(state):
            yield event
            if "message" in event or "industry_data" in event:
                result = event
        yield result or {}
