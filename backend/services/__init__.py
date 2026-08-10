"""Backend services 子包。

提供横切关注点的服务抽象:
- llm_factory: 统一 LLM 工厂（Zen 免费优先、国内原厂与聚合服务回退）
- search: 检索 provider 抽象层(SearchProvider Protocol + 具体实现)
- mongodb / pdf_service: 已有的辅助服务
"""

from .llm_factory import get_llm
from .search import (
    CrawledPage,
    SearchProvider,
    SearchResult,
    get_search_provider,
)

__all__ = [
    "get_llm",
    "SearchProvider",
    "SearchResult",
    "CrawledPage",
    "get_search_provider",
]
