import logging

from langchain_core.messages import AIMessage

from ..classes import InputState, ResearchState
from ..classes.state import job_status
from ..services.search import get_search_provider

logger = logging.getLogger(__name__)


class GroundingNode:
    """Gathers initial grounding data about the company."""

    def __init__(self) -> None:
        # 通过统一的 SearchProvider 调用,默认走 Tavily,可由
        # SEARCH_PROVIDER 环境变量切换为其他实现(Phase 2)。
        self.search = get_search_provider()

    async def initial_search(self, state: InputState):
        """Initial search and yield events"""
        company = state.get("company", "Unknown Company")
        job_id = state.get("job_id")
        msg = f"🎯 Initiating research for {company}...\n"

        # Emit initialization event
        event = {
            "type": "research_init",
            "company": company,
            "message": f"Initiating research for {company}",
            "step": "Initializing",
        }

        if job_id:
            try:
                if job_id in job_status:
                    job_status[job_id]["events"].append(event)
            except Exception as e:
                logger.error(f"Error appending research_init event: {e}")

        yield event

        site_scrape = {}

        # Only attempt extraction if we have a URL
        if url := state.get("company_url"):
            msg += f"\n🌐 Crawling company website: {url}"
            logger.info(f"Starting website analysis for {url}")

            # Emit crawl start event
            event = {
                "type": "crawl_start",
                "url": url,
                "message": f"Crawling company website: {url}",
                "step": "Website Crawl",
            }

            if job_id:
                try:
                    if job_id in job_status:
                        job_status[job_id]["events"].append(event)
                except Exception as e:
                    logger.error(f"Error appending crawl_start event: {e}")

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
                    logger.info(
                        f"Successfully crawled {len(site_scrape)} pages from website"
                    )
                    msg += f"\n✅ Successfully crawled {len(site_scrape)} pages from website"
                    yield {
                        "type": "crawl_success",
                        "pages_found": len(site_scrape),
                        "message": f"Successfully crawled {len(site_scrape)} pages from website",
                        "step": "Initial Site Scrape",
                    }
                else:
                    logger.warning("No content found in crawl results")
                    msg += "\n⚠️ No content found in website crawl"
                    yield {
                        "type": "crawl_warning",
                        "message": "⚠️ No content found in provided URL",
                        "step": "Initial Site Scrape",
                    }
            except Exception as e:
                logger.error(
                    "Website crawl error, exception_type=%s",
                    type(e).__name__,
                )
                error_msg = "⚠️ Website content crawl unavailable"
                msg += f"\n{error_msg}"
                yield {
                    "type": "crawl_error",
                    "reason": "crawl_failed",
                    "message": error_msg,
                    "step": "Initial Site Scrape",
                    "continue_research": True,
                }
        else:
            msg += "\n⏩ No company URL provided, proceeding directly to research phase"
            yield {
                "type": "no_url",
                "message": "No company URL provided, proceeding directly to research phase",
                "step": "Initializing",
            }
        # Add context about what information we have
        context_data = {}
        if hq := state.get("hq_location"):
            msg += f"\n📍 Company HQ: {hq}"
            context_data["hq_location"] = hq
        if industry := state.get("industry"):
            msg += f"\n🏭 Industry: {industry}"
            context_data["industry"] = industry

        # Initialize ResearchState with input information
        research_state = {
            # Copy input fields
            "company": state.get("company"),
            "company_url": state.get("company_url"),
            "hq_location": state.get("hq_location"),
            "industry": state.get("industry"),
            "job_id": state.get("job_id"),
            # Initialize research fields
            "messages": [AIMessage(content=msg)],
            "site_scrape": site_scrape,
        }

        # If there was an error in the initial crawl, store it in the state
        if "⚠️ Error crawling website content:" in msg:
            research_state["error"] = error_str

        yield {"type": "grounding_complete", "site_pages": len(site_scrape)}
        yield research_state

    async def run(self, state: InputState) -> ResearchState:
        """Run grounding - note: for now returns directly, events can be captured if needed"""
        # For compatibility, we call the generator but don't yield
        # The calling code can be updated later to consume events
        result = None
        async for event in self.initial_search(state):
            # The last yield should be the research_state (a dict with state fields)
            # Earlier yields are event dicts with "type" field
            if isinstance(event, dict) and "type" not in event:
                result = event
        return result if result else {}
