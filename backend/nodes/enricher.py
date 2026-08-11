import asyncio
import logging

from langchain_core.messages import AIMessage

from ..classes import ResearchState
from ..classes.state import job_status
from ..services.search import SearchProvider, get_search_provider

logger = logging.getLogger(__name__)


class Enricher:
    """使用正文内容增强筛选后的文档。"""

    def __init__(self, *, search: SearchProvider | None = None) -> None:
        # 默认 TavilyProvider,API key 由 provider 内部校验
        self.search = search if search is not None else get_search_provider()
        self.batch_size = 20

    async def fetch_single_content(self, url: str) -> dict[str, str]:
        """抓取单个 URL 的正文内容。"""
        try:
            pages = await self.search.extract([url])
            if pages:
                return {url: pages[0].raw_content}
        except Exception as exc:
            logger.error(
                "抓取 URL 正文失败，url=%s，异常类型=%s",
                url,
                type(exc).__name__,
            )
            return {url: ""}
        return {url: ""}

    async def fetch_raw_content(self, urls: list[str]) -> dict[str, str]:
        """在限流约束下并行抓取多个 URL 的正文。"""
        raw_contents = {}

        # 创建抓取批次
        batches = [
            urls[i : i + self.batch_size] for i in range(0, len(urls), self.batch_size)
        ]

        # 在限流约束下处理批次
        semaphore = asyncio.Semaphore(3)  # 并发批次最多为 3

        async def process_batch(batch_urls: list[str]) -> dict[str, str]:
            async with semaphore:
                tasks = [self.fetch_single_content(url) for url in batch_urls]
                results = await asyncio.gather(*tasks)

                batch_contents = {}
                for result in results:
                    batch_contents.update(result)
                return batch_contents

        # 处理全部批次
        batch_results = await asyncio.gather(
            *[process_batch(batch) for batch in batches]
        )

        # 合并各批次结果
        for batch_result in batch_results:
            raw_contents.update(batch_result)

        return raw_contents

    async def enrich_data(self, state: ResearchState) -> ResearchState:
        """使用正文内容增强筛选后的文档。"""
        company = state.get("company", "未知公司")
        job_id = state.get("job_id")

        logger.info("开始增强公司数据：%s，job_id=%s", company, job_id)
        msg = [f"📚 正在增强 {company} 的筛选数据："]

        # 逐类处理筛选后的数据
        data_types = {
            "financial_data": "💰 财务",
            "news_data": "📰 新闻",
            "industry_data": "🏭 行业",
            "company_data": "🏢 公司",
        }

        # 创建并行处理任务
        enrichment_tasks = []
        for data_field, label in data_types.items():
            curated_field = f"curated_{data_field}"
            curated_docs = state.get(curated_field, {})

            if not curated_docs:
                msg.append(f"\n• 没有待增强的{label}文档")
                continue

            # 查找需要补充正文的文档
            docs_needing_content = {
                url: doc
                for url, doc in curated_docs.items()
                if not doc.get("raw_content")
            }

            if not docs_needing_content:
                msg.append(f"\n• 全部{label}文档都已包含正文")
                continue

            msg.append(f"\n• 正在增强 {len(docs_needing_content)} 份{label}文档……")

            # 从字段名提取类别，例如 curated_financial_data 对应 financial
            category = curated_field.replace("curated_", "").replace("_data", "")

            enrichment_tasks.append(
                {
                    "field": curated_field,
                    "label": label,
                    "category": category,
                    "docs": docs_needing_content,
                    "curated_docs": curated_docs,
                }
            )

        # 发送增强开始事件
        if enrichment_tasks and job_id:
            try:
                if job_id in job_status:
                    job_status[job_id]["events"].append(
                        {
                            "type": "enrichment",
                            "message": f"正在增强 {len(enrichment_tasks)} 个数据类别",
                        }
                    )
            except Exception as exc:
                logger.error(
                    "追加 enrichment 事件失败，异常类型=%s",
                    type(exc).__name__,
                )

        # 并行处理全部类别
        if enrichment_tasks:

            async def process_category(task):
                try:
                    raw_contents = await self.fetch_raw_content(
                        list(task["docs"].keys())
                    )

                    enriched_count = 0
                    for url, content in raw_contents.items():
                        if content:  # 仅加入非空正文
                            task["curated_docs"][url]["raw_content"] = content
                            enriched_count += 1

                    # 将增强后的文档写入状态
                    state[task["field"]] = task["curated_docs"]

                    return {
                        "label": task["label"],
                        "category": task["category"],
                        "enriched": enriched_count,
                        "total": len(task["docs"]),
                    }
                except Exception as exc:
                    logger.error(
                        "处理类别失败，类别=%s，异常类型=%s",
                        task["label"],
                        type(exc).__name__,
                    )
                    return {
                        "label": task["label"],
                        "category": task["category"],
                        "enriched": 0,
                        "total": len(task["docs"]),
                    }

            # 并行处理全部类别
            results = await asyncio.gather(
                *[process_category(task) for task in enrichment_tasks]
            )

            # 汇总增强结果并发送完成事件
            for result in results:
                msg.append(
                    f"\n  ✓ {result['label']}：已增强 "
                    f"{result['enriched']}/{result['total']} 份文档"
                )

                # 为每个类别发送增强完成事件
                if job_id:
                    try:
                        if job_id in job_status:
                            job_status[job_id]["events"].append(
                                {
                                    "type": "enrichment",
                                    "category": result[
                                        "category"
                                    ],  # 事件字段使用类别代码而非显示标签
                                    "enriched": result["enriched"],
                                    "total": result["total"],
                                    "message": (
                                        f"已增强 {result['enriched']}/{result['total']} "
                                        f"份{result['label']}文档"
                                    ),
                                }
                            )
                    except Exception as exc:
                        logger.error(
                            "追加 enrichment 完成事件失败，异常类型=%s",
                            type(exc).__name__,
                        )

        # 将增强结果写入状态消息
        state.setdefault("messages", []).append(AIMessage(content="\n".join(msg)))

        return state

    async def run(self, state: ResearchState) -> ResearchState:
        try:
            return await self.enrich_data(state)
        except Exception as exc:
            logger.error("增强流程失败，异常类型=%s", type(exc).__name__)
            return state
