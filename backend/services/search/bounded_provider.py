"""一个调研任务内共享的独立检索和正文请求预算。"""

from __future__ import annotations

import asyncio
from typing import Any

from . import CrawledPage, SearchProvider, SearchResult
from .native_utils import is_public_web_url

DEFAULT_MAX_SEARCHES = 16
DEFAULT_MAX_FETCHES = 10
DEFAULT_WEB_CONCURRENCY = 3


class SearchBudgetExceeded(RuntimeError):
    """当前任务已用完检索次数，不能再发起付费请求。"""


class BoundedSearchProvider:
    """在同一任务的四路分析器间共享上限，重复正文只请求一次。"""

    def __init__(
        self,
        provider: SearchProvider,
        *,
        max_searches: int = DEFAULT_MAX_SEARCHES,
        max_fetches: int = DEFAULT_MAX_FETCHES,
        concurrency: int = DEFAULT_WEB_CONCURRENCY,
    ) -> None:
        if min(max_searches, max_fetches, concurrency) <= 0:
            raise ValueError("网页请求预算和并发数必须为正数")
        self.provider = provider
        self._remaining_searches = max_searches
        self._max_fetches = max_fetches
        self._semaphore = asyncio.Semaphore(concurrency)
        self._fetches: dict[str, asyncio.Task[list[CrawledPage]]] = {}

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        time_range: str | None = None,
        **kwargs: Any,
    ) -> list[SearchResult]:
        if not query.strip():
            return []
        # 在首次 await 前完成准入，同一事件循环并发调用不能越过计数。
        if self._remaining_searches <= 0:
            raise SearchBudgetExceeded("本次调研的网页搜索次数已用完")
        self._remaining_searches -= 1
        async with self._semaphore:
            return await self.provider.search(
                query, max_results=max_results, time_range=time_range, **kwargs
            )

    async def _fetch(self, url: str) -> list[CrawledPage]:
        async with self._semaphore:
            pages = await self.provider.extract([url])
        return [page for page in pages if page.url == url and page.raw_content][:1]

    async def extract(self, urls: list[str], **_kwargs: Any) -> list[CrawledPage]:
        """预留每个新 URL 后再调度；失败也消耗本任务尝试预算。"""
        tasks = []
        for url in dict.fromkeys(urls):
            if not is_public_web_url(url):
                continue
            if url not in self._fetches:
                if len(self._fetches) >= self._max_fetches:
                    continue
                self._fetches[url] = asyncio.create_task(self._fetch(url))
            tasks.append(self._fetches[url])
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            page for result in results if isinstance(result, list) for page in result
        ]

    async def crawl(self, url: str, *, max_pages: int = 5, **kwargs: Any):
        return await self.provider.crawl(url, max_pages=max_pages, **kwargs)


__all__ = ["BoundedSearchProvider", "SearchBudgetExceeded"]
