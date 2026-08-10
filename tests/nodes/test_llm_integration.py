"""LLM 工厂在 3 个节点(researcher / briefing / editor)中的集成测试。

策略:
- 把每个节点模块里 ``from ...services.llm_factory import get_llm`` 引入的本地
  ``get_llm`` 名字 monkeypatch 成返回 fake LLM 的桩函数
- ``GenericFakeChatModel`` 自带 ``astream`` 真实流式行为(按字符分片),足以
  验证"3 个节点能成功初始化、astream 正常产出 chunk"的契约
- 不发真实 HTTP,不依赖具体 ``OPENAI_API_KEY`` / ``GEMINI_API_KEY``

注意 BaseResearcher 还需要 ``TAVILY_API_KEY``,因为构造期会实例化
``AsyncTavilyClient``(Task 3.4 才会把它替换为 SearchProvider)。
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

# === 测试夹具 ===


def _make_fake_llm() -> GenericFakeChatModel:
    """每次返回一个**新的** fake LLM(``messages`` 是 iter,会被消费完)。"""
    return GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(content="第一段 fake 输出"),
                AIMessage(content="第二段 fake 输出"),
                AIMessage(content="第三段 fake 输出"),
            ]
        )
    )


@pytest.fixture
def fake_llm() -> GenericFakeChatModel:
    return _make_fake_llm()


@pytest.fixture
def patch_get_llm(
    monkeypatch: pytest.MonkeyPatch, fake_llm: GenericFakeChatModel
) -> GenericFakeChatModel:
    """把 3 个节点本地 ``get_llm`` 引用都替换成返回 ``fake_llm`` 的桩函数。

    每个节点模块都 ``from ...services.llm_factory import get_llm``,
    这种 import 形式会在模块命名空间中绑定一个本地名字,所以必须
    分别 patch,而不能只 patch ``backend.services.llm_factory.get_llm``。
    """

    def _stub(role: str, **overrides: Any) -> GenericFakeChatModel:
        return fake_llm

    monkeypatch.setattr("backend.nodes.researchers.base.get_llm", _stub)
    monkeypatch.setattr("backend.nodes.briefing.get_llm", _stub)
    monkeypatch.setattr("backend.nodes.editor.get_llm", _stub)
    return fake_llm


# === 节点初始化 ===


def test_base_researcher_init_uses_factory(
    monkeypatch: pytest.MonkeyPatch,
    patch_get_llm: GenericFakeChatModel,
) -> None:
    """BaseResearcher 不再要求 OPENAI_API_KEY,LLM 来自工厂。"""
    monkeypatch.setenv("TAVILY_API_KEY", "fake-tavily-key")
    # 故意不设 OPENAI_API_KEY / OPENROUTER_API_KEY,验证不再依赖具体 key

    from backend.nodes.researchers.base import BaseResearcher

    r = BaseResearcher()
    assert r.llm is patch_get_llm


def test_base_researcher_still_requires_tavily_key(
    monkeypatch: pytest.MonkeyPatch,
    patch_get_llm: GenericFakeChatModel,
) -> None:
    """检索 provider 仍校验 TAVILY_API_KEY,缺失时抛 RuntimeError。

    Task 2.1 的 LLM 重构后,Task 3.4 又把 search 也改走 provider,
    TAVILY_API_KEY 校验从 BaseResearcher 转移到 TavilyProvider.__init__,
    错误类型从 ValueError 变为 RuntimeError(由 provider 抛出)。
    """
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    from backend.nodes.researchers.base import BaseResearcher

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        BaseResearcher()


def test_briefing_init_uses_factory(
    patch_get_llm: GenericFakeChatModel,
) -> None:
    """Briefing 不再要求 GEMINI_API_KEY。"""
    from backend.nodes.briefing import Briefing

    b = Briefing()
    assert b.llm is patch_get_llm


def test_editor_init_uses_factory(
    patch_get_llm: GenericFakeChatModel,
) -> None:
    """Editor 不再直接拿 OPENAI_API_KEY。"""
    from backend.nodes.editor import Editor

    e = Editor()
    assert e.llm is patch_get_llm


# === astream 产出 chunk(直接打 fake LLM)===


@pytest.mark.asyncio
async def test_fake_llm_astream_yields_multiple_chunks() -> None:
    """先确认 fake LLM 自身能逐 token 流式产出,作为后续测试的前提。"""
    llm = _make_fake_llm()

    chunks = []
    async for chunk in llm.astream([HumanMessage(content="hi")]):
        chunks.append(chunk)

    assert len(chunks) > 1, "GenericFakeChatModel 应当按字符/分隔符多次 yield"
    assert "".join(c.content for c in chunks) == "第一段 fake 输出"


# === astream 产出 chunk(走节点真实 LCEL 链)===


@pytest.mark.asyncio
async def test_researcher_chain_astream_yields_chunks(
    monkeypatch: pytest.MonkeyPatch,
    patch_get_llm: GenericFakeChatModel,
) -> None:
    """researcher 节点(``self.llm``)能跑通完整 LCEL ``astream`` 链路。"""
    monkeypatch.setenv("TAVILY_API_KEY", "fake-tavily-key")

    from backend.nodes.researchers.base import BaseResearcher

    r = BaseResearcher()
    chain = ChatPromptTemplate.from_messages([("user", "research {company}")]) | r.llm

    chunks = []
    async for chunk in chain.astream({"company": "宁德时代"}):
        chunks.append(chunk)

    assert len(chunks) > 1
    assert "".join(c.content for c in chunks) == "第一段 fake 输出"


@pytest.mark.asyncio
async def test_briefing_chain_ainvoke_returns_full(
    patch_get_llm: GenericFakeChatModel,
) -> None:
    """briefing 节点用 ``ainvoke``(非流式),也应能返回完整字符串。"""
    from backend.nodes.briefing import Briefing

    b = Briefing()
    chain = (
        ChatPromptTemplate.from_messages([("user", "brief {company}")])
        | b.llm
        | StrOutputParser()
    )

    result = await chain.ainvoke({"company": "宁德时代"})
    assert result == "第一段 fake 输出"


@pytest.mark.asyncio
async def test_editor_chain_astream_yields_chunks(
    patch_get_llm: GenericFakeChatModel,
) -> None:
    """editor 节点是面向 SSE 的流式输出场景,必须保证 astream 能产 chunk。"""
    from backend.nodes.editor import Editor

    e = Editor()
    chain = (
        ChatPromptTemplate.from_messages([("user", "edit {company}")])
        | e.llm
        | StrOutputParser()
    )

    chunks = []
    async for chunk in chain.astream({"company": "宁德时代"}):
        chunks.append(chunk)

    assert len(chunks) > 1, "editor 流式管线必须能逐段 yield 给前端 SSE"
    assert all(isinstance(c, str) for c in chunks), "StrOutputParser 应输出 str"
    assert "".join(chunks) == "第一段 fake 输出"
