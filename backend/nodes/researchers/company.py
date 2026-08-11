from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

from ...classes import ResearchState
from ...prompts import COMPANY_ANALYZER_QUERY_PROMPT
from ...services.search import SearchProvider
from .base import BaseResearcher


class CompanyAnalyzer(BaseResearcher):
    def __init__(
        self,
        *,
        search: SearchProvider | None = None,
        llm: Runnable[Any, Any] | None = None,
    ) -> None:
        super().__init__(search=search, llm=llm)
        self.analyst_type = "company_analyzer"

    async def analyze(self, state: ResearchState):
        """分析公司信息并持续产出事件。"""
        company = state.get("company", "未知公司")

        # 生成搜索词并持续产出事件
        queries = []
        async for event in self.generate_queries(state, COMPANY_ANALYZER_QUERY_PROMPT):
            yield event
            if event.get("type") == "queries_complete":
                queries = event.get("queries", [])

        # 记录公司分析子查询
        subqueries_msg = "🔍 公司分析子查询：\n" + "\n".join(
            [f"• {query}" for query in queries]
        )
        state.setdefault("messages", []).append(AIMessage(content=subqueries_msg))

        # 以站点抓取数据作为初始内容
        company_data = dict[str, Any](state.get("site_scrape", {}))

        # 搜索并合并文档，同时持续产出事件
        documents = {}
        async for event in self.search_documents(state, queries):
            yield event
            if event.get("type") == "search_complete":
                documents = event.get("merged_docs", {})

        company_data.update(documents)

        # 更新状态
        completion_msg = f"🏢 公司分析器为 {company} 找到 {len(company_data)} 份文档"
        state.setdefault("messages", []).append(AIMessage(content=completion_msg))
        state["company_data"] = company_data

        yield {
            "type": "analysis_complete",
            "data_type": "company_data",
            "count": len(company_data),
        }
        yield {"message": [completion_msg], "company_data": company_data}

    async def run(self, state: ResearchState):
        """执行分析并产出全部事件。"""
        result = None
        async for event in self.analyze(state):
            yield event
            if "message" in event or "company_data" in event:
                result = event
        yield result or {}
