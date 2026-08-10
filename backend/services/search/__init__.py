"""检索 provider 抽象层。

核心设计:
- ``SearchProvider`` 是一个 ``Protocol``(结构化类型),任何实现了 ``search``
  / ``crawl`` / ``extract`` 的类都自动符合接口
- ``SearchResult`` / ``CrawledPage`` 为统一的返回数据结构,各 provider 必须
  把原生响应映射为这两种类型
- ``get_search_provider()`` 工厂根据 ``SEARCH_PROVIDER`` 环境变量挑选实现

接口设计参考了 Tavily、Bocha AI、Serper 三家的公开 API 取并集,
provider 专有的扩展参数通过 ``**kwargs`` 透传。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class SearchResult:
    """单条搜索结果。

    Attributes:
        url: 文档原始 URL(必有)
        title: 文档标题(可能为空字符串)
        content: 摘要或正文片段
        score: 相关性打分,0~1。provider 不提供时填 0.0
        published_date: 发布日期(ISO 字符串或 None)
        raw: provider 原始返回的整条字典,保留所有未在标准字段中的元数据
    """

    url: str
    title: str
    content: str
    score: float = 0.0
    published_date: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CrawledPage:
    """单个被抓取的页面。

    Attributes:
        url: 页面 URL
        raw_content: 抓取到的纯文本(可能很长)
        title: 页面标题(可选)
        raw: provider 原始返回字典
    """

    url: str
    raw_content: str
    title: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SearchProvider(Protocol):
    """检索 provider 接口。

    所有方法都是 ``async``,因为上层节点都是 ``asyncio`` 风格。
    任何实现了这三个方法的类自动符合本接口(structural typing)。
    """

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        time_range: str | None = None,
        **kwargs: Any,
    ) -> list[SearchResult]:
        """对 ``query`` 执行 web 搜索,返回相关性排序的结果列表。"""
        ...

    async def crawl(
        self,
        url: str,
        *,
        max_pages: int = 5,
        **kwargs: Any,
    ) -> list[CrawledPage]:
        """从 ``url`` 起抓取站点页面,返回多页正文。"""
        ...

    async def extract(
        self,
        urls: list[str],
        **kwargs: Any,
    ) -> list[CrawledPage]:
        """从给定 URL 列表批量抽取正文(单页提取,不递归)。"""
        ...


# === 工厂 ===

# 已注册的 provider 名 → 工厂函数(惰性 import,避免没装的依赖被强制加载)
_PROVIDERS: dict[str, str] = {
    "tavily": "backend.services.search.tavily_provider:TavilyProvider",
}


def get_search_provider() -> SearchProvider:
    """根据 ``SEARCH_PROVIDER`` 环境变量返回对应实现。

    默认 ``"tavily"``。

    Raises:
        ValueError: 未知 provider 名。
    """
    name = os.getenv("SEARCH_PROVIDER", "tavily").strip().lower()

    if name not in _PROVIDERS:
        raise ValueError(
            f"未知的 SEARCH_PROVIDER: {name!r}。当前已注册: {sorted(_PROVIDERS.keys())}"
        )

    # 按 "module:Class" 形式延迟 import
    module_path, class_name = _PROVIDERS[name].split(":")
    import importlib

    module = importlib.import_module(module_path)
    provider_cls = getattr(module, class_name)
    return provider_cls()


__all__ = [
    "SearchProvider",
    "SearchResult",
    "CrawledPage",
    "get_search_provider",
]
