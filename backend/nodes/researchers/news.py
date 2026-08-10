from typing import Any

from langchain_core.messages import AIMessage

from ...classes import ResearchState
from ...prompts import NEWS_SCANNER_QUERY_PROMPT
from .base import BaseResearcher


class NewsScanner(BaseResearcher):
    def __init__(self) -> None:
        super().__init__()
        self.analyst_type = "news_analyzer"

    async def analyze(self, state: ResearchState):
        """分析新闻信息并持续产出事件。"""
        company = state.get("company", "未知公司")

        # 生成搜索词并持续产出事件
        queries = []
        async for event in self.generate_queries(state, NEWS_SCANNER_QUERY_PROMPT):
            yield event
            if event.get("type") == "queries_complete":
                queries = event.get("queries", [])

        # 记录新闻分析子查询
        subqueries_msg = "🔍 新闻分析子查询：\n" + "\n".join(
            [f"• {query}" for query in queries]
        )
        state.setdefault("messages", []).append(AIMessage(content=subqueries_msg))

        # 以站点抓取数据作为初始内容
        news_data = dict[str, Any](state.get("site_scrape", {}))

        # 搜索并合并文档，同时持续产出事件
        documents = {}
        async for event in self.search_documents(state, queries):
            yield event
            if event.get("type") == "search_complete":
                documents = event.get("merged_docs", {})

        news_data.update(documents)

        # 更新状态
        completion_msg = f"📰 新闻扫描器为 {company} 找到 {len(news_data)} 份文档"
        state.setdefault("messages", []).append(AIMessage(content=completion_msg))
        state["news_data"] = news_data

        yield {
            "type": "analysis_complete",
            "data_type": "news_data",
            "count": len(news_data),
        }
        yield {"message": [completion_msg], "news_data": news_data}

    async def run(self, state: ResearchState):
        """执行分析并产出全部事件。"""
        result = None
        async for event in self.analyze(state):
            yield event
            if "message" in event or "news_data" in event:
                result = event
        yield result or {}
