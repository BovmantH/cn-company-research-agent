"""使用真实十节点图验证状态通道；厂商和正文调用全部为内存桩。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from backend.graph import Graph, ResearchDependencies
from backend.nodes.editor import Editor
from backend.services.search import CrawledPage, SearchResult

SOURCE_URL = "https://example.com/research"
SOURCE_TITLE = "官方产品说明"
GRAPH_NODES = {
    "grounding",
    "financial_analyst",
    "news_scanner",
    "industry_analyst",
    "company_analyst",
    "collector",
    "curator",
    "enricher",
    "briefing",
    "editor",
}


class MemorySearchProvider:
    def __init__(self) -> None:
        self.search_queries: list[str] = []
        self.extracted_urls: list[str] = []

    async def search(self, query: str, **_kwargs: Any) -> list[SearchResult]:
        self.search_queries.append(query)
        return [
            SearchResult(
                url=SOURCE_URL,
                title=SOURCE_TITLE,
                content="示例公司的产品与经营信息。",
                score=0.9,
            )
        ]

    async def crawl(self, _url: str, **_kwargs: Any) -> list[CrawledPage]:
        return []

    async def extract(self, urls: list[str], **_kwargs: Any) -> list[CrawledPage]:
        self.extracted_urls.extend(urls)
        return [CrawledPage(url=url, raw_content="可验证的页面正文。") for url in urls]


@pytest.fixture
def memory_graph(monkeypatch: pytest.MonkeyPatch) -> tuple[Graph, MemorySearchProvider]:
    """保留所有节点及并行分支真实行为，只替换远端模型和格式清扫输出。"""

    async def preserve_report(_editor: Editor, content: str) -> AsyncIterator[str]:
        yield content

    monkeypatch.setattr(Editor, "content_sweep", preserve_report)
    search = MemorySearchProvider()
    dependencies = ResearchDependencies(
        search=search,
        researcher_llm=RunnableLambda(lambda _: AIMessage(content="公司调研查询")),
        briefing_llm=RunnableLambda(lambda _: AIMessage(content="分类调研简报。")),
        editor_llm=RunnableLambda(lambda _: AIMessage(content="# 示例公司调研报告")),
    )
    return Graph(company="示例公司", dependencies=dependencies), search


@pytest.mark.asyncio
async def test_web_graph_preserves_source_titles_through_all_ten_nodes(
    memory_graph: tuple[Graph, MemorySearchProvider],
) -> None:
    graph, search = memory_graph
    updates = [update async for update in graph.run(thread={})]

    assert {node for update in updates for node in update} == GRAPH_NODES
    assert len(search.search_queries) == 4
    assert SOURCE_URL in search.extracted_urls
    report = next(
        update["editor"]["report"] for update in updates if "editor" in update
    )
    assert SOURCE_TITLE in report
    assert SOURCE_URL in report


@pytest.mark.asyncio
async def test_compiled_graph_returns_report_and_source_metadata(
    memory_graph: tuple[Graph, MemorySearchProvider],
) -> None:
    graph, _search = memory_graph
    result = await graph.compile().ainvoke(graph.input_state)

    assert result["company"] == "示例公司"
    assert result["report"].startswith("# 示例公司调研报告")
    assert result["references"] == [SOURCE_URL]
    assert result["reference_titles"][SOURCE_URL] == SOURCE_TITLE
    assert result["reference_info"][SOURCE_URL]["title"] == SOURCE_TITLE
