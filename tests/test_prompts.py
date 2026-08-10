"""``backend.prompts`` 中文化后的渲染验收测试。

Phase 1 的 prompt 中文化没法跑真实 LLM 端到端验收(免费额度有限,且不进 CI),
所以做一组**结构化静态校验**作为替代验收:

1. **占位符未丢失**: 中文化前后,每个 prompt 的 ``{...}`` 占位符
   名字与数量一一对应 —— 这是 spec 的硬性要求
2. **``.format(...)`` 能成功渲染**: 用真实可能出现的中文输入,
   ``str.format()`` 不抛 ``KeyError`` / ``ValueError``
3. **章节小标题映射齐全**: 例如 briefing prompt 中应当出现「核心产品/服务」、
   「领导团队」等中文标题,而不应该残留对应英文
4. **否定指令保留**: spec Scenario 要求等效中文否定指令(「不得提及『未找到信息』」)

如果将来跑了真实端到端,可以删掉这个测试或在 spec 上把它降级为冒烟。
"""

from __future__ import annotations

import re

import pytest

from backend.prompts import (
    BRIEFING_ANALYSIS_INSTRUCTION,
    COMPANY_ANALYZER_QUERY_PROMPT,
    COMPANY_BRIEFING_PROMPT,
    COMPILE_CONTENT_PROMPT,
    CONTENT_SWEEP_PROMPT,
    CONTENT_SWEEP_SYSTEM_MESSAGE,
    EDITOR_SYSTEM_MESSAGE,
    FINANCIAL_ANALYZER_QUERY_PROMPT,
    FINANCIAL_BRIEFING_PROMPT,
    INDUSTRY_ANALYZER_QUERY_PROMPT,
    INDUSTRY_BRIEFING_PROMPT,
    NEWS_BRIEFING_PROMPT,
    NEWS_SCANNER_QUERY_PROMPT,
    QUERY_FORMAT_GUIDELINES,
)

# === 占位符抽取工具 ===


_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _placeholders(template: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(template))


# === 占位符断言 ===


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        (COMPANY_BRIEFING_PROMPT, {"company", "industry", "hq_location"}),
        (INDUSTRY_BRIEFING_PROMPT, {"company", "industry", "hq_location"}),
        (FINANCIAL_BRIEFING_PROMPT, {"company", "industry", "hq_location"}),
        (NEWS_BRIEFING_PROMPT, {"company", "industry", "hq_location"}),
        (COMPANY_ANALYZER_QUERY_PROMPT, {"company", "industry"}),
        (FINANCIAL_ANALYZER_QUERY_PROMPT, {"company", "industry"}),
        (INDUSTRY_ANALYZER_QUERY_PROMPT, {"company", "industry"}),
        (NEWS_SCANNER_QUERY_PROMPT, {"company"}),
        (QUERY_FORMAT_GUIDELINES, {"company"}),
        (
            COMPILE_CONTENT_PROMPT,
            {"company", "industry", "hq_location", "combined_content"},
        ),
        (
            CONTENT_SWEEP_PROMPT,
            {"company", "industry", "hq_location", "content"},
        ),
    ],
)
def test_placeholders_preserved(prompt: str, expected: set[str]) -> None:
    """中文化后,每个 prompt 的占位符集合必须与原版完全一致。"""
    assert _placeholders(prompt) == expected


def test_no_orphan_placeholders() -> None:
    """system message 类常量不应误引入占位符(LangChain 会当成必填变量)。"""
    assert _placeholders(EDITOR_SYSTEM_MESSAGE) == set()
    assert _placeholders(CONTENT_SWEEP_SYSTEM_MESSAGE) == set()
    assert _placeholders(BRIEFING_ANALYSIS_INSTRUCTION) == set()


# === .format(...) 真实渲染 ===


_DUMMY = {
    "company": "宁德时代",
    "industry": "新能源",
    "hq_location": "福建宁德",
    "combined_content": "(占位:多份简报正文)",
    "content": "(占位:报告中间稿)",
}


@pytest.mark.parametrize(
    "prompt",
    [
        COMPANY_BRIEFING_PROMPT,
        INDUSTRY_BRIEFING_PROMPT,
        FINANCIAL_BRIEFING_PROMPT,
        NEWS_BRIEFING_PROMPT,
        COMPANY_ANALYZER_QUERY_PROMPT,
        FINANCIAL_ANALYZER_QUERY_PROMPT,
        INDUSTRY_ANALYZER_QUERY_PROMPT,
        NEWS_SCANNER_QUERY_PROMPT,
        QUERY_FORMAT_GUIDELINES,
        COMPILE_CONTENT_PROMPT,
        CONTENT_SWEEP_PROMPT,
    ],
)
def test_prompt_renders_with_chinese_inputs(prompt: str) -> None:
    """每个 prompt 用「宁德时代」等真实中文输入渲染必须不抛异常。"""
    needed = _placeholders(prompt)
    args = {k: _DUMMY[k] for k in needed}

    rendered = prompt.format(**args)

    # 渲染后必须把所有 placeholder 都替换掉
    assert _placeholders(rendered) == set()
    # 公司名必须出现在渲染结果中(只要原 prompt 里包含 {company} 占位符)
    if "company" in needed:
        assert _DUMMY["company"] in rendered


# === 章节中文标题映射齐全 ===


_REQUIRED_HEADERS = {
    COMPANY_BRIEFING_PROMPT: [
        "### 核心产品/服务",
        "### 领导团队",
        "### 目标市场",
        "### 核心差异化优势",
        "### 商业模式",
    ],
    INDUSTRY_BRIEFING_PROMPT: [
        "### 市场概览",
        "### 直接竞争对手",
        "### 竞争优势",
        "### 市场挑战",
    ],
    FINANCIAL_BRIEFING_PROMPT: [
        "### 融资与投资",
        "### 营收模式",
    ],
    NEWS_BRIEFING_PROMPT: [
        "### 重要公告",
        "### 合作伙伴",
        "### 荣誉与媒体报道",
    ],
}


@pytest.mark.parametrize(
    ("prompt", "headers"),
    list(_REQUIRED_HEADERS.items()),
    ids=["company", "industry", "financial", "news"],
)
def test_chinese_section_headers_present(prompt: str, headers: list[str]) -> None:
    for header in headers:
        assert header in prompt, f"prompt 中缺少中文小标题: {header!r}"


def test_editor_main_headers_present() -> None:
    """editor 输出报告骨架的 5 个 ## 主标题必须中文化。"""
    for header in [
        "## 公司概览",
        "## 行业概览",
        "## 财务概览",
        "## 新闻动态",
    ]:
        assert header in COMPILE_CONTENT_PROMPT
        assert header in CONTENT_SWEEP_PROMPT
    # 参考文献是 sweep 阶段才组装的,只在 sweep prompt 中要求
    assert "## 参考文献" in CONTENT_SWEEP_PROMPT


# === 残留英文章节检查 ===


_FORBIDDEN_ENGLISH_HEADERS = [
    "### Core Product/Service",
    "### Leadership Team",
    "### Target Market",
    "### Key Differentiators",
    "### Business Model",
    "### Market Overview",
    "### Direct Competition",
    "### Competitive Advantages",
    "### Market Challenges",
    "### Funding & Investment",
    "### Revenue Model",
    "### Major Announcements",
    "### Partnerships",
    "### Recognition",
    "## Company Overview",
    "## Industry Overview",
    "## Financial Overview",
    "## References",
]


@pytest.mark.parametrize("header", _FORBIDDEN_ENGLISH_HEADERS)
def test_no_english_headers_remain(header: str) -> None:
    """中文化后,原英文小/大标题在所有 prompt 字符串中应零残留。"""
    all_prompts = "\n".join(
        [
            COMPANY_BRIEFING_PROMPT,
            INDUSTRY_BRIEFING_PROMPT,
            FINANCIAL_BRIEFING_PROMPT,
            NEWS_BRIEFING_PROMPT,
            COMPILE_CONTENT_PROMPT,
            CONTENT_SWEEP_PROMPT,
            EDITOR_SYSTEM_MESSAGE,
            CONTENT_SWEEP_SYSTEM_MESSAGE,
            COMPANY_ANALYZER_QUERY_PROMPT,
            FINANCIAL_ANALYZER_QUERY_PROMPT,
            INDUSTRY_ANALYZER_QUERY_PROMPT,
            NEWS_SCANNER_QUERY_PROMPT,
            QUERY_FORMAT_GUIDELINES,
            BRIEFING_ANALYSIS_INSTRUCTION,
        ]
    )
    assert header not in all_prompts, f"英文标题残留: {header!r}"


# === 否定指令保留(spec scenario) ===


@pytest.mark.parametrize(
    "prompt",
    [
        COMPANY_BRIEFING_PROMPT,
        INDUSTRY_BRIEFING_PROMPT,
        FINANCIAL_BRIEFING_PROMPT,
        NEWS_BRIEFING_PROMPT,
    ],
)
def test_negative_instruction_preserved(prompt: str) -> None:
    """spec scenario「否定指令保留」: 4 类 briefing 都要有「不得提及」之类的中文等效。"""
    # 接受多种合理表述
    candidates = [
        "不得提及",
        "不要提及",
        "禁止提及",
        "未找到信息",
        "暂无数据",
    ]
    matched = [w for w in candidates if w in prompt]
    assert matched, "prompt 中找不到「未找到信息/暂无数据」类的否定指令"
