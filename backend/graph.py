import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import SystemMessage
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

logger = logging.getLogger(__name__)


class Graph:
    def __init__(
        self, company=None, url=None, hq_location=None, industry=None, job_id=None
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

        # 初始化工作流节点
        self._init_nodes()
        self._build_workflow()

    def _init_nodes(self):
        """初始化全部工作流节点。"""
        self.ground = GroundingNode()
        self.financial_analyst = FinancialAnalyst()
        self.news_scanner = NewsScanner()
        self.industry_analyst = IndustryAnalyzer()
        self.company_analyst = CompanyAnalyzer()
        self.collector = Collector()
        self.curator = Curator()
        self.enricher = Enricher()
        self.briefing = Briefing()
        self.editor = Editor()

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
