import logging
import re
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def extract_domain_name(url: str) -> str:
    """从 URL 中提取可读的网站名称。"""
    try:
        # 移除协议和 www 前缀
        domain = url.lower()
        for prefix in ["https://", "http://", "www."]:
            if domain.startswith(prefix):
                domain = domain[len(prefix) :]

        # 获取主域名部分，即首个斜杠或查询参数之前的内容
        domain = domain.split("/")[0].split("?")[0]

        # 提取域名主体，例如从 example.com 提取 example
        parts = domain.split(".")
        if len(parts) >= 2:
            main_name = parts[0]
            # 将名称首字母大写
            return main_name.capitalize()
        return domain.capitalize()
    except Exception as exc:
        logger.error(
            "提取域名失败，url=%s，异常类型=%s",
            url,
            type(exc).__name__,
        )
        return "网站"


def extract_title_from_url_path(url: str) -> str:
    """从 URL 路径中提取有意义的标题。"""
    try:
        # 移除协议、www 前缀和域名
        path = url.lower()
        for prefix in ["https://", "http://", "www."]:
            if path.startswith(prefix):
                path = path[len(prefix) :]

        # 移除域名
        if "/" in path:
            path = path.split("/", 1)[1]
        else:
            path = ""

        # 清理路径并生成标题
        if path:
            # 移除文件扩展名和查询参数
            path = path.split("?")[0].split("#")[0]
            if path.endswith("/"):
                path = path[:-1]

            # 将连字符和下划线替换为空格
            path = path.replace("-", " ").replace("_", " ").replace("/", " - ")

            # 将单词首字母大写
            title = " ".join(word.capitalize() for word in path.split())

            # 标题仍然过长时进行截断
            if len(title) > 100:
                title = title[:97] + "..."

            return title
        return ""
    except Exception as exc:
        logger.error("从 URL 路径提取标题失败，异常类型=%s", type(exc).__name__)
        return ""


def clean_title(title: str) -> str:
    """移除标题中的日期、末尾句点或引号，并按需截断。"""
    if not title:
        return ""

    original_title = title

    title = title.strip().rstrip(".").strip("\"'")
    title = re.sub(r"^\d{4}[-\s]*\d{1,2}[-\s]*\d{1,2}[-\s]*", "", title)
    title = title.strip("- ").strip()

    # 清理后标题为空时返回空字符串
    if not title:
        logger.warning("标题清理后为空：%s", original_title)
        return ""

    # 标题发生变化时记录日志
    if title != original_title:
        logger.info("标题已从 %s 清理为 %s", original_title, title)

    return title


def normalize_url(url: str) -> str:
    """移除查询参数和片段，规范化 URL。"""
    try:
        if not url:
            return ""

        # 确保 URL 包含协议
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        parsed = urlparse(url)
        normalized_url = parsed._replace(query="", fragment="").geturl().rstrip("/")

        return normalized_url
    except Exception as exc:
        logger.error(
            "规范化 URL 失败，url=%s，异常类型=%s",
            url,
            type(exc).__name__,
        )
        return url


def extract_website_name_from_domain(domain: str) -> str:
    """从域名中提取可读的网站名称。"""
    if domain.startswith("www."):
        domain = domain[4:]  # 移除 www 前缀

    # 提取域名主体，例如从 example.com 提取 example
    website_name = domain.split(".")[0].capitalize()

    # 处理特殊域名
    if website_name == "Com":
        # 尝试从第二段域名中提取更合适的名称
        parts = domain.split(".")
        if len(parts) > 1:
            website_name = parts[0].capitalize()

    return website_name


def process_references_from_search_results(
    state: Dict[str, Any],
) -> Tuple[List[str], Dict[str, str], Dict[str, Dict[str, Any]]]:
    """处理搜索结果中的引用，并返回优先引用、标题和附加信息。"""
    all_top_references = []

    # 从全部数据类型中收集带分数的引用
    data_types = [
        "curated_company_data",
        "curated_industry_data",
        "curated_financial_data",
        "curated_news_data",
    ]

    # 记录引用处理开始
    logger.info("开始处理搜索结果中的引用")

    for data_type in data_types:
        if curated_data := state.get(data_type, {}):
            for url, doc in curated_data.items():
                try:
                    # 确保分数有效
                    if "evaluation" in doc and "overall_score" in doc["evaluation"]:
                        score = float(doc["evaluation"]["overall_score"])
                    else:
                        # 可用时回退到原始分数
                        score = float(doc.get("score", 0))

                    logger.info(
                        "在 %s 中发现引用：URL=%s，分数=%.4f",
                        data_type,
                        url,
                        score,
                    )
                    all_top_references.append((url, score))
                except (KeyError, ValueError, TypeError) as exc:
                    logger.warning(
                        "处理引用分数失败：url=%s，数据类型=%s，异常类型=%s",
                        url,
                        data_type,
                        type(exc).__name__,
                    )
                    continue

    logger.info("去重前共收集 %s 条引用", len(all_top_references))

    # 按分数降序排列引用
    all_top_references.sort(key=lambda x: float(x[1]), reverse=True)

    # 记录去重前分数最高的 20 条引用，用于验证排序
    logger.info("去重前分数最高的 20 条引用：")
    for i, (url, score) in enumerate(all_top_references[:20]):
        logger.info("第 %s 条：分数=%.4f，URL=%s", i + 1, score, url)

    # 使用集合保存唯一 URL，每个 URL 只保留分数最高的版本
    seen_urls = set()
    unique_references = []
    reference_titles = {}  # 保存引用标题
    reference_info = {}  # 保存 MLA 格式引用所需的附加信息

    for url, score in all_top_references:
        # 跳过无效 URL
        if not url or not url.startswith(("http://", "https://")):
            logger.info("跳过无效 URL：%s", url)
            continue

        # 规范化 URL
        normalized_url = normalize_url(url)

        if normalized_url not in seen_urls:
            seen_urls.add(normalized_url)
            unique_references.append((normalized_url, score))

            # 为网站引用提取域名
            parsed = urlparse(url)
            domain = parsed.netloc

            # 查找并保存该 URL 的标题及其他信息
            title = None
            website_name = None

            # 在全部数据类型中查找文档信息
            for data_type in data_types:
                if not title and (curated_data := state.get(data_type, {})):
                    for doc in curated_data.values():
                        if doc.get("url") == url:
                            title = doc.get("title", "")
                            if title:
                                # 清理标题
                                title = clean_title(title)
                                if title and title.strip() and title != url:
                                    reference_titles[normalized_url] = title
                                    logger.info(
                                        "已找到 URL 标题，url=%s，title=%s", url, title
                                    )
                                    break

            # 未找到标题时记录日志
            if not title:
                logger.info("未找到有效标题，url=%s", url)

            # 从域名中提取更合适的网站名称
            website_name = extract_website_name_from_domain(domain)

            # 保存 MLA 引用所需的附加信息
            reference_info[normalized_url] = {
                "title": title or "",
                "domain": domain,
                "website": website_name,
                "url": normalized_url,
                "score": score,
            }
            logger.info("已保存引用信息：url=%s，分数=%.4f", normalized_url, score)

    # 再次按分数排列唯一引用，确保顺序正确
    unique_references.sort(key=lambda x: float(x[1]), reverse=True)

    # 按分数记录唯一引用，用于验证排序
    logger.info("去重后得到 %s 条唯一引用", len(unique_references))
    logger.info("按分数排序后的唯一引用：")
    for i, (url, score) in enumerate(unique_references):
        logger.info("第 %s 条：分数=%.4f，URL=%s", i + 1, score, url)

    # 最多保留 10 条唯一引用
    top_references = unique_references[:10]
    top_reference_urls = [url for url, _ in top_references]

    # 记录最终选择的前 10 条引用
    logger.info("最终选出前 %s 条引用：", len(top_reference_urls))
    for i, url in enumerate(top_reference_urls):
        score = next((s for u, s in unique_references if u == url), 0)
        logger.info("第 %s 条：分数=%.4f，URL=%s", i + 1, score, url)

    return top_reference_urls, reference_titles, reference_info


def format_reference_for_markdown(reference_entry: Dict[str, Any]) -> str:
    """为 Markdown 输出格式化一条引用。"""
    website = reference_entry.get("website", "")
    title = reference_entry.get("title", "")
    url = reference_entry.get("url", "")

    # 确保存在网站名称
    if not website or website.strip() == "":
        website = extract_domain_name(url)

    # 确保存在标题
    if not title or title.strip() == "" or title == url:
        # 尝试从 URL 中提取有意义的标题
        title = extract_title_from_url_path(url)

        # 仍无标题时使用默认格式
        if not title:
            title = f"来自 {website} 的信息"

    # 格式：* 网站名. "标题." URL
    return f'* {website}. "{title}." {url}'


def extract_link_info(line: str) -> tuple[str, str]:
    """从 Markdown 链接中提取标题和 URL。"""
    try:
        # 先清理可能干扰链接解析的 JSON 残留
        line = re.sub(r'",?\s*"pdf_url":.+$', "", line)

        # 检查链接前带网站名和标题的 MLA 格式引用
        # 格式：* 网站名. "标题." [URL](URL)
        mla_match = re.match(r'\*?\s*(.*?)\s*\.\s*"(.*?)\."\s*\[(.*?)\]\((.*?)\)', line)
        if mla_match:
            website = clean_title(mla_match.group(1))
            title = clean_title(mla_match.group(2))
            link_text = clean_title(mla_match.group(3))
            url = clean_title(mla_match.group(4))

            # 网站名为空或仅为句点时，从 URL 提取
            if not website or website == ".":
                website = extract_domain_name(url)

            # PDF 格式："网站名. 标题. URL"
            return f"{website}. {title}. {link_text}", url

        # 回退处理标准 Markdown 链接
        match = re.match(r"\[(.*?)\]\((.*?)\)", line)
        if match:
            title = clean_title(match.group(1))
            url = clean_title(match.group(2))
            # 标题本身就是相同 URL 时直接使用 URL
            if title.startswith("http") and title == url:
                return url, url
            return title, url

        logger.debug("当前行未匹配到链接：%s", line)
        return "", ""
    except Exception as exc:
        logger.error(
            "提取链接信息失败，异常类型=%s",
            type(exc).__name__,
        )
        return "", ""


def format_references_section(
    references: List[str],
    reference_info: Dict[str, Dict[str, Any]],
    reference_titles: Dict[str, str],
) -> str:
    """格式化最终报告的参考资料章节。"""
    if not references:
        return ""

    logger.info("正在为报告格式化 %s 条引用", len(references))

    # 创建包含所需信息的引用条目列表
    reference_entries = []
    for ref in references:
        info = reference_info.get(ref, {})
        website = info.get("website", "")
        title = info.get("title", "")
        score = info.get("score", 0)

        # reference_info 中没有标题时尝试从 reference_titles 获取
        if not title or title.strip() == "":
            title = reference_titles.get(ref, "")
            logger.info("引用 %s 使用 reference_titles 中的标题：%s", ref, title)

        domain = info.get("domain", "")

        # 没有标题时使用 URL
        if not title or title.strip() == "" or title == ref:
            title = ref
            logger.info("引用 %s 没有标题，将 URL 用作标题", ref)

        # 没有网站名称时从 URL 提取
        if not website or website.strip() == "":
            website = extract_domain_name(ref)
            logger.info("引用 %s 没有网站名称，已提取为 %s", ref, website)

        # 创建包含全部信息的引用条目
        entry = {
            "website": website,
            "title": title,
            "url": ref,
            "domain": domain,
            "score": score,
        }
        logger.info("已创建引用条目：%s", entry)
        reference_entries.append(entry)

    # 保持传入的引用顺序，该顺序应已按分数排列
    # 这样可以保留 process_references_from_search_results 生成的前 10 名顺序
    logger.info("按分数保持引用顺序")

    # 按 MLA 样式格式化引用
    reference_lines = ["\n## 参考文献"]
    for entry in reference_entries:
        reference_line = format_reference_for_markdown(entry)
        reference_lines.append(reference_line)
        logger.info("已添加引用：%s", reference_line)

    reference_text = "\n".join(reference_lines)
    logger.info("参考资料章节已完成，共 %s 条", len(reference_entries))

    return reference_text
