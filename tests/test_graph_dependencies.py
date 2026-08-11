from typing import Any

from backend.graph import Graph, ResearchDependencies


class StubSearchProvider:
    async def search(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []

    async def crawl(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []

    async def extract(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []


def test_graph_uses_dependencies_from_the_current_research_task() -> None:
    search = StubSearchProvider()
    researcher_llm = object()
    briefing_llm = object()
    editor_llm = object()
    dependencies = ResearchDependencies(
        search=search,
        researcher_llm=researcher_llm,
        briefing_llm=briefing_llm,
        editor_llm=editor_llm,
    )

    graph = Graph(company="示例公司", dependencies=dependencies)

    assert graph.ground.search is search
    assert graph.enricher.search is search
    assert graph.company_analyst.search is search
    assert graph.financial_analyst.search is search
    assert graph.industry_analyst.search is search
    assert graph.news_scanner.search is search
    assert graph.company_analyst.llm is researcher_llm
    assert graph.financial_analyst.llm is researcher_llm
    assert graph.industry_analyst.llm is researcher_llm
    assert graph.news_scanner.llm is researcher_llm
    assert graph.briefing.llm is briefing_llm
    assert graph.editor.llm is editor_llm
