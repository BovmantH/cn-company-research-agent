#!/usr/bin/env python
"""供应商兼容性冒烟测试——P1 入选门（对应 tasks.md §4）。

执行三个动作，验证供应商的官方 OpenAI 兼容端点是否真正兼容：
  1) 普通完成        ── 同步 invoke
  2) 流式完成        ── 异步 astream
  3) max_tokens 限制 ── 验证参数被尊重

任一动作失败则该供应商不符合 P1 入选标准，推迟到后续阶段。

用法:
    # 先导出对应供应商的 Key
    export ZHIPUAI_API_KEY=sk-...
    python scripts/vendor_smoke_test.py --vendor glm

    # 已在 VENDOR_REGISTRY 中的供应商也可以执行回归
    export DEEPSEEK_API_KEY=sk-...
    python scripts/vendor_smoke_test.py --vendor deepseek
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Optional

# 让脚本能从仓库根目录直接跑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 默认 GBK 控制台无法打印部分 emoji / 中文符号,统一切到 UTF-8
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

from langchain_core.messages import HumanMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

from backend.services.llm_factory import VENDOR_REGISTRY  # noqa: E402

# 待冒烟测试通过后再合入 VENDOR_REGISTRY 的候选供应商。
# 已在注册表中的供应商使用注册表配置。
# 这里的 base_url 是各家"官方"OpenAI 兼容端点;实际跑测试时可通过
# 可通过 LLM_BASE_URL_<VENDOR> 环境变量覆盖，例如令牌套餐对应的镜像端点。
CANDIDATE_REGISTRY: dict[str, dict[str, str]] = {
    "glm": {
        # 官方 OpenAI 兼容文档: https://docs.bigmodel.cn/cn/guide/develop/openai/introduction
        # glm-4.7-flash 是免费版（200K 上下文），适合冒烟测试
        "env_key": "ZAI_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "model": "glm-4.7-flash",
    },
    "minimax": {
        # 官方文档: https://platform.minimaxi.com/docs/api-reference/text-openai-api
        # 国内站默认。国际站走 https://api.minimax.io/v1 (key 不通用)。
        # MiniMax-M2.7-highspeed 是性价比版本，适合冒烟测试
        "env_key": "MINIMAX_API_KEY",
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M2.7-highspeed",
    },
}


@dataclass
class TestResult:
    name: str
    passed: bool
    detail: str = ""


def _make_client(
    vendor: str, *, streaming: bool, max_tokens: Optional[int] = None
) -> tuple[ChatOpenAI, str]:
    """构造 ChatOpenAI，根据供应商来源从注册表或候选配置中取值。

    若设置了 ``LLM_BASE_URL_<VENDOR>`` 环境变量,则覆盖默认 base_url
    (与 LLMFactory 的优先级保持一致)。
    """
    if vendor in VENDOR_REGISTRY:
        cfg = VENDOR_REGISTRY[vendor]
        api_key = os.getenv(cfg.env_key)
        if not api_key:
            print(f"[setup] 环境变量 {cfg.env_key} 未设置", file=sys.stderr)
            sys.exit(2)
        model = cfg.default_model("researcher")
        base_url = cfg.base_url
    elif vendor in CANDIDATE_REGISTRY:
        cfg_d = CANDIDATE_REGISTRY[vendor]
        api_key = os.getenv(cfg_d["env_key"])
        if not api_key:
            print(f"[setup] 环境变量 {cfg_d['env_key']} 未设置", file=sys.stderr)
            sys.exit(2)
        model = cfg_d["model"]
        base_url = cfg_d["base_url"]
    else:
        print(
            f"[setup] 未知 vendor {vendor!r}。可选:"
            f"{sorted(set(VENDOR_REGISTRY) | set(CANDIDATE_REGISTRY))}",
            file=sys.stderr,
        )
        sys.exit(2)

    base_url_override = os.getenv(f"LLM_BASE_URL_{vendor.upper()}")
    if base_url_override:
        base_url = base_url_override

    kwargs: dict = dict(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
        streaming=streaming,
    )
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs), model


def test_basic_invoke(vendor: str) -> TestResult:
    """G-1: 普通完成。"""
    try:
        client, _ = _make_client(vendor, streaming=False)
        resp = client.invoke([HumanMessage(content="用中文回答:1+1 等于几?")])
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        text = text.strip()
        if not text:
            return TestResult("basic_invoke", False, "返回内容为空")
        return TestResult(
            "basic_invoke", True, f"返回长度 {len(text)},片段:{text[:40]!r}"
        )
    except Exception as e:  # noqa: BLE001
        return TestResult("basic_invoke", False, f"{type(e).__name__}: {e}")


async def _astream_once(vendor: str) -> tuple[int, str]:
    client, _ = _make_client(vendor, streaming=True)
    chunks = 0
    parts: list[str] = []
    async for chunk in client.astream([HumanMessage(content="数到 5,用中文。")]):
        chunks += 1
        if isinstance(chunk.content, str):
            parts.append(chunk.content)
    return chunks, "".join(parts)


def test_streaming(vendor: str) -> TestResult:
    """G-2: 流式完成。chunks > 0 算通过(一次性返回的 vendor 也算"协议兼容")。"""
    try:
        chunks, text = asyncio.run(_astream_once(vendor))
        if chunks == 0:
            return TestResult("streaming", False, "未收到任何 chunk")
        return TestResult(
            "streaming",
            True,
            f"chunks={chunks},合计长度 {len(text)},片段:{text[:40]!r}",
        )
    except Exception as e:  # noqa: BLE001
        return TestResult("streaming", False, f"{type(e).__name__}: {e}")


def test_max_tokens(vendor: str) -> TestResult:
    """G-3: max_tokens=32 应限制输出长度。被静默忽略 → 不通过。"""
    try:
        client, _ = _make_client(vendor, streaming=False, max_tokens=32)
        resp = client.invoke(
            [
                HumanMessage(content="详细介绍上海这座城市,至少 500 字。"),
            ]
        )
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        # 32 token 中文 ≈ 30~60 字符,给 200 字符容差(留出 think 标签等开销)
        if len(text) > 200:
            return TestResult(
                "max_tokens",
                False,
                f"max_tokens=32 被忽略,实际返回 {len(text)} 字符",
            )
        return TestResult(
            "max_tokens",
            True,
            f"返回 {len(text)} 字符,片段:{text[:40]!r}",
        )
    except Exception as e:  # noqa: BLE001
        return TestResult("max_tokens", False, f"{type(e).__name__}: {e}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vendor",
        required=True,
        help="待测试的供应商名称：已在注册表内的 "
        "deepseek/qwen/kimi/openrouter/openai，或候选 glm/mimo/minimax",
    )
    args = parser.parse_args()
    vendor = args.vendor.strip().lower()

    print(f"\n=== 供应商冒烟测试：{vendor} ===\n")
    _, model = _make_client(vendor, streaming=False)
    print(f"使用模型 model={model}\n")

    results = [
        test_basic_invoke(vendor),
        test_streaming(vendor),
        test_max_tokens(vendor),
    ]

    print("-" * 60)
    for r in results:
        flag = "通过" if r.passed else "失败"
        print(f"[{flag}] {r.name:<14} {r.detail}")
    print("-" * 60)

    if all(r.passed for r in results):
        print(f"\n[OK] {vendor} 通过全部冒烟测试，可纳入 VENDOR_REGISTRY。\n")
        return 0
    print(f"\n[X] {vendor} 存在失败项，不符合 P1 入选标准，推迟到后续阶段。\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
