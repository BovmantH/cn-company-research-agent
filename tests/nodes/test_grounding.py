from __future__ import annotations

import pytest

from backend.nodes.grounding import GroundingNode


class FailingSearchProvider:
    async def crawl(self, *_args, **_kwargs):
        raise RuntimeError("Authorization: Bearer upstream-secret")


@pytest.mark.asyncio
async def test_crawl_failure_records_only_safe_state_error() -> None:
    node = object.__new__(GroundingNode)
    node.search = FailingSearchProvider()

    events = [
        event
        async for event in node.initial_search(
            {"company": "示例科技", "company_url": "https://example.com"}
        )
    ]

    assert events[-1]["error"] == "⚠️ Website content crawl unavailable"
    assert "upstream-secret" not in repr(events)
