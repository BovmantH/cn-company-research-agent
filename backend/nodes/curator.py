import logging
from urllib.parse import urljoin, urlparse

from langchain_core.messages import AIMessage

from ..classes import ResearchState
from ..classes.state import job_status
from ..utils.references import process_references_from_search_results

logger = logging.getLogger(__name__)


class Curator:
    def __init__(self) -> None:
        self.relevance_threshold = 0.4
        logger.info(
            "筛选器已初始化，相关性阈值=%s",
            self.relevance_threshold,
        )

    def evaluate_documents(self, docs: list, context: dict[str, str]) -> list:
        """根据搜索服务返回的相关性分数评估文档。"""
        if not docs:
            return []

        logger.info("正在评估 %s 份文档", len(docs))

        evaluated_docs = []
        try:
            # 使用搜索服务提供的相关性分数逐份评估文档
            for doc in docs:
                try:
                    # 确保分数可以转换为浮点数
                    relevance_score = float(doc.get("score", 0))  # 未提供分数时默认为 0

                    # 公司官网属于一方信息，无论分数高低都予以保留
                    is_company_website = doc.get("source") == "company_website"

                    # 保留相关性达标的文档或公司官网数据
                    if (
                        relevance_score >= self.relevance_threshold
                        or is_company_website
                    ):
                        reason = (
                            "公司官网"
                            if is_company_website
                            else f"分数 {relevance_score:.4f}"
                        )
                        logger.info(
                            "保留文档（%s）：%s",
                            reason,
                            doc.get("title", "无标题"),
                        )

                        evaluated_doc = {
                            **doc,
                            "evaluation": {
                                "overall_score": relevance_score,  # 以浮点数存储
                                "query": doc.get("query", ""),
                            },
                        }
                        evaluated_docs.append(evaluated_doc)
                    else:
                        logger.info(
                            "文档相关性低于阈值，分数=%.4f，标题=%s",
                            relevance_score,
                            doc.get("title", "无标题"),
                        )
                except (ValueError, TypeError) as exc:
                    logger.warning(
                        "处理文档分数失败，异常类型=%s",
                        type(exc).__name__,
                    )
                    continue

        except Exception as exc:
            logger.error("文档评估失败，异常类型=%s", type(exc).__name__)
            return []

        # 返回前按相关性分数排序
        evaluated_docs.sort(
            key=lambda x: float(x["evaluation"]["overall_score"]), reverse=True
        )
        logger.info("返回 %s 份已评估文档", len(evaluated_docs))

        return evaluated_docs

    async def curate_data(self, state: ResearchState) -> ResearchState:
        """根据搜索服务的相关性分数筛选全部已收集数据。"""
        company = state.get("company", "未知公司")
        job_id = state.get("job_id")
        logger.info("开始筛选公司数据：%s，job_id=%s", company, job_id)

        industry = state.get("industry", "未知行业")
        context = {
            "company": company,
            "industry": industry,
            "hq_location": state.get("hq_location", "未知地点"),
        }

        msg = [f"🔍 正在筛选 {company} 的调研数据"]

        data_types = {
            "financial_data": ("💰 财务", "financial"),
            "news_data": ("📰 新闻", "news"),
            "industry_data": ("🏭 行业", "industry"),
            "company_data": ("🏢 公司", "company"),
        }

        # 逐类处理调研数据
        for data_field, (emoji, doc_type) in data_types.items():
            data = state.get(data_field, {})
            if not data:
                continue

            # 筛选并规范化 URL
            unique_docs = {}
            for url, doc in data.items():
                try:
                    parsed = urlparse(url)
                    if not parsed.scheme:
                        url = urljoin("https://", url)
                    clean_url = parsed._replace(query="", fragment="").geturl()
                    if clean_url not in unique_docs:
                        doc["url"] = clean_url
                        doc["doc_type"] = doc_type
                        unique_docs[clean_url] = doc
                except Exception:
                    continue

            docs = list(unique_docs.values())
            msg.append(f"\n{emoji}：发现 {len(docs)} 份文档")

            evaluated_docs = self.evaluate_documents(docs, context)

            # 发送包含总数的筛选事件
            if job_id:
                try:
                    if job_id in job_status:
                        job_status[job_id]["events"].append(
                            {
                                "type": "curation",
                                "category": doc_type,
                                "total": len(evaluated_docs) if evaluated_docs else 0,
                                "message": f"正在筛选 {doc_type} 文档",
                            }
                        )
                except Exception as exc:
                    logger.error(
                        "追加 curation 事件失败，异常类型=%s",
                        type(exc).__name__,
                    )

            if not evaluated_docs:
                msg.append("  ⚠️ 未找到相关文档")
                continue

            # 按相关性分数筛选并排序
            relevant_docs = {doc["url"]: doc for doc in evaluated_docs}
            sorted_items = sorted(
                relevant_docs.items(),
                key=lambda item: item[1]["evaluation"]["overall_score"],
                reverse=True,
            )

            # 每个类别最多保留 30 份文档
            if len(sorted_items) > 30:
                sorted_items = sorted_items[:30]
            relevant_docs = dict(sorted_items)

            if relevant_docs:
                msg.append(f"  ✓ 已保留 {len(relevant_docs)} 份相关文档")
                logger.info(
                    "%s 类别保留 %s 份分数达到阈值的文档",
                    doc_type,
                    len(relevant_docs),
                )
            else:
                msg.append("  ⚠️ 没有文档达到相关性阈值")
                logger.info("%s 类别没有文档达到相关性阈值", doc_type)

            # 将筛选后的文档写入状态
            state[f"curated_{data_field}"] = relevant_docs

        # 使用引用模块处理参考资料
        top_reference_urls, reference_titles, reference_info = (
            process_references_from_search_results(state)
        )
        logger.info("为报告选出前 %s 条参考资料", len(top_reference_urls))

        # 将参考资料及其标题写入状态
        state.setdefault("messages", []).append(AIMessage(content="\n".join(msg)))
        state["references"] = top_reference_urls
        state["reference_titles"] = reference_titles
        state["reference_info"] = reference_info

        return state

    async def run(self, state: ResearchState) -> ResearchState:
        return await self.curate_data(state)
