from langchain_core.messages import AIMessage

from ..classes import ResearchState


class Collector:
    """在筛选前收集并整理全部调研数据。"""

    async def collect(self, state: ResearchState) -> ResearchState:
        """收集调研数据，并检查各类数据是否存在。"""
        company = state.get("company", "未知公司")
        msg = [f"📦 正在收集 {company} 的调研数据："]

        # 检查各类调研数据
        research_types = {
            "financial_data": "💰 财务",
            "news_data": "📰 新闻",
            "industry_data": "🏭 行业",
            "company_data": "🏢 公司",
        }

        for data_field, label in research_types.items():
            data = state.get(data_field, {})
            if data:
                msg.append(f"• {label}：已收集 {len(data)} 份文档")
            else:
                msg.append(f"• {label}：未找到数据")

        # 将收集结果写入状态消息
        state.setdefault("messages", []).append(AIMessage(content="\n".join(msg)))

        return state

    async def run(self, state: ResearchState) -> ResearchState:
        return await self.collect(state)
