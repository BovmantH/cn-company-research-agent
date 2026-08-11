import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.runnables import Runnable
from langgraph.graph import StateGraph

from .classes.state import InputState
from .nodes import GroundingNode
from .nodes.briefing import Briefing
from .nodes.collector import Collector
from .nodes.curator import Curator
from .nodes.editor import Editor
from .nodes.enricher import Enricher
from .nodes.researchers import (
    CompanyAnalyzer,
    FinancialAnalyst,
    IndustryAnalyzer,
    NewsScanner,
)
from .services.llm_factory import get_llm
from .services.search import SearchProvider, get_search_provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResearchDependencies:
    """封装单次调研使用的模型与检索实例，避免跨任务共享密钥配置。"""

    search: SearchProvider
    researcher_llm: Runnable[Any, Any]
    briefing_llm: Runnable[Any, Any]
    editor_llm: Runnable[Any, Any]

    @classmethod
    def from_server_config(cls) -> "ResearchDependencies":
        """使用部署者的服务端配置构造默认依赖，保持旧调用方式兼容。"""
        return cls(
            search=get_search_provider(),
            researcher_llm=get_llm("researcher"),
            briefing_llm=get_llm("briefing", streaming=False),
            editor_llm=get_llm("editor", streaming=True),
        )


class Graph:
    def __init__(
        self,
        company=None,
        url=None,
        hq_location=None,
        industry=None,
        job_id=None,
        dependencies: ResearchDependencies | None = None,
    ):
        # 初始化图输入状态
        self.input_state = InputState(
            company=company,
            company_url=url,
            hq_location=hq_location,
            industry=industry,
            job_id=job_id,
            messages=[SystemMessage(content="资深调研员开始调查")],
        )

        # 依赖属于当前调研任务；用户自带 Key 后不会写入进程环境变量。
        self.dependencies = dependencies or ResearchDependencies.from_server_config()
        self._init_nodes()
        self._build_workflow()

    def _init_nodes(self):
        """初始化全部工作流节点。"""
        self.ground = GroundingNode(search=self.dependencies.search)
        self.financial_analyst = FinancialAnalyst(
            search=self.dependencies.search,
            llm=self.dependencies.researcher_llm,
        )
        self.news_scanner = NewsScanner(
            search=self.dependencies.search,
            llm=self.dependencies.researcher_llm,
        )
        self.industry_analyst = IndustryAnalyzer(
            search=self.dependencies.search,
            llm=self.dependencies.researcher_llm,
        )
        self.company_analyst = CompanyAnalyzer(
            search=self.dependencies.search,
            llm=self.dependencies.researcher_llm,
        )
        self.collector = Collector()
        self.curator = Curator()
        self.enricher = Enricher(search=self.dependencies.search)
        self.briefing = Briefing(llm=self.dependencies.briefing_llm)
        self.editor = Editor(llm=self.dependencies.editor_llm)

    def _build_workflow(self):
        """配置状态图工作流。"""
        self.workflow = StateGraph(InputState)

        # 注册节点及其处理函数
        self.workflow.add_node("grounding", self.ground.run)
        self.workflow.add_node("financial_analyst", self.financial_analyst.run)
        self.workflow.add_node("news_scanner", self.news_scanner.run)
        self.workflow.add_node("industry_analyst", self.industry_analyst.run)
        self.workflow.add_node("company_analyst", self.company_analyst.run)
        self.workflow.add_node("collector", self.collector.run)
        self.workflow.add_node("curator", self.curator.run)
        self.workflow.add_node("enricher", self.enricher.run)
        self.workflow.add_node("briefing", self.briefing.run)
        self.workflow.add_node("editor", self.editor.run)

        # 配置工作流边
        self.workflow.set_entry_point("grounding")
        self.workflow.set_finish_point("editor")

        research_nodes = [
            "financial_analyst",
            "news_scanner",
            "industry_analyst",
            "company_analyst",
        ]

        # 将信息落地节点连接到全部调研节点
        for node in research_nodes:
            self.workflow.add_edge("grounding", node)
            self.workflow.add_edge(node, "collector")

        # 连接其余处理节点
        self.workflow.add_edge("collector", "curator")
        self.workflow.add_edge("curator", "enricher")
        self.workflow.add_edge("enricher", "briefing")
        self.workflow.add_edge("briefing", "editor")

    async def run(self, thread: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """执行调研工作流。"""
        compiled_graph = self.workflow.compile()

        async for state in compiled_graph.astream(self.input_state, thread):
            yield state

    def compile(self):
        graph = self.workflow.compile()
        return graph
