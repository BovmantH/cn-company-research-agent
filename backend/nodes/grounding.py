import logging

from langchain_core.messages import AIMessage

from ..classes import InputState, ResearchState
from ..classes.state import job_status
from ..services.search import get_search_provider

logger = logging.getLogger(__name__)


class GroundingNode:
    """收集公司的初始背景数据。"""

    def __init__(self) -> None:
        # 通过统一的 SearchProvider 调用,默认走 Tavily,可由
        # SEARCH_PROVIDER 环境变量切换为其他实现(Phase 2)。
        self.search = get_search_provider()

    async def initial_search(self, state: InputState):
        """执行初始搜索并持续产出事件。"""
        company = state.get("company", "未知公司")
        job_id = state.get("job_id")
        msg = f"🎯 开始调研 {company}……\n"

        # 发送初始化事件
        event = {
            "type": "research_init",
            "company": company,
            "message": f"开始调研 {company}",
            "step": "正在初始化",
        }

        if job_id:
            try:
                if job_id in job_status:
                    job_status[job_id]["events"].append(event)
            except Exception as exc:
                logger.error(
                    "追加 research_init 事件失败，异常类型=%s",
                    type(exc).__name__,
                )

        yield event

        site_scrape = {}
        crawl_error_message: str | None = None

        # 仅在提供网址时抓取站点内容
        if url := state.get("company_url"):
            msg += f"\n🌐 正在抓取公司网站：{url}"
            logger.info("开始分析公司网站：%s", url)

            # 发送抓取开始事件
            event = {
                "type": "crawl_start",
                "url": url,
                "message": f"正在抓取公司网站：{url}",
                "step": "网站抓取",
            }

            if job_id:
                try:
                    if job_id in job_status:
                        job_status[job_id]["events"].append(event)
                except Exception as exc:
                    logger.error(
                        "追加 crawl_start 事件失败，异常类型=%s",
                        type(exc).__name__,
                    )

            yield event

            try:
                logger.info("通过 SearchProvider 发起站点抓取")
                pages = await self.search.crawl(
                    url,
                    max_pages=50,  # 等价于原 Tavily 调用的 max_breadth=50
                    instructions="Find any pages that will help us understand the company's business, products, services, and any other relevant information.",
                    max_depth=1,
                    extract_depth="advanced",
                )

                site_scrape = {}
                for page in pages:
                    # provider 已过滤掉空 raw_content,这里 page.url 兜底用入口 url
                    page_url = page.url or url
                    site_scrape[page_url] = {
                        "raw_content": page.raw_content,
                        "source": "company_website",
                    }

                if site_scrape:
                    logger.info("已成功从网站抓取 %s 个页面", len(site_scrape))
                    msg += f"\n✅ 已成功从网站抓取 {len(site_scrape)} 个页面"
                    yield {
                        "type": "crawl_success",
                        "pages_found": len(site_scrape),
                        "message": f"已成功抓取 {len(site_scrape)} 个网站页面",
                        "step": "初始站点抓取",
                    }
                else:
                    logger.warning("站点抓取结果中未发现内容")
                    msg += "\n⚠️ 站点抓取未发现内容"
                    yield {
                        "type": "crawl_warning",
                        "message": "⚠️ 提供的网址中未发现内容",
                        "step": "初始站点抓取",
                    }
            except Exception as e:
                logger.error(
                    "网站抓取失败，异常类型=%s",
                    type(e).__name__,
                )
                error_msg = "⚠️ 网站内容暂时无法抓取"
                crawl_error_message = error_msg
                msg += f"\n{error_msg}"
                yield {
                    "type": "crawl_error",
                    "reason": "crawl_failed",
                    "message": error_msg,
                    "step": "初始站点抓取",
                    "continue_research": True,
                }
        else:
            msg += "\n⏩ 未提供公司网址，直接进入调研阶段"
            yield {
                "type": "no_url",
                "message": "未提供公司网址，直接进入调研阶段",
                "step": "正在初始化",
            }
        # 补充已有的公司背景信息
        context_data = {}
        if hq := state.get("hq_location"):
            msg += f"\n📍 公司总部：{hq}"
            context_data["hq_location"] = hq
        if industry := state.get("industry"):
            msg += f"\n🏭 所属行业：{industry}"
            context_data["industry"] = industry

        # 使用输入信息初始化 ResearchState
        research_state = {
            # 复制输入字段
            "company": state.get("company"),
            "company_url": state.get("company_url"),
            "hq_location": state.get("hq_location"),
            "industry": state.get("industry"),
            "job_id": state.get("job_id"),
            # 初始化调研字段
            "messages": [AIMessage(content=msg)],
            "site_scrape": site_scrape,
        }

        # 只保存稳定文案；上游异常正文不能进入 Graph 状态或后续 SSE。
        if crawl_error_message is not None:
            research_state["error"] = crawl_error_message

        yield {"type": "grounding_complete", "site_pages": len(site_scrape)}
        yield research_state

    async def run(self, state: InputState) -> ResearchState:
        """执行背景信息收集；当前直接返回结果，事件可按需接入。"""
        # 为保持兼容，仅消费生成器而不向外转发事件
        # 调用方后续可以按需改为直接消费这些事件
        result = None
        async for event in self.initial_search(state):
            # 最后一次产出应为 research_state，即不含 type 的状态字典
            # 更早产出的均为带 type 字段的事件字典
            if isinstance(event, dict) and "type" not in event:
                result = event
        return result if result else {}
