"""cn-company-research 的后端包。

LLM 调用统一通过 ``backend.services.llm_factory.get_llm`` 走 OpenRouter,
检索调用统一通过 ``backend.services.search.get_search_provider`` 走
``SearchProvider`` 接口(默认 Tavily)。本模块仅做 ``.env`` 加载与启动告警。
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from .graph import Graph

# 配置日志记录器
logger = logging.getLogger(__name__)

# 从 .env 文件加载环境变量
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    logger.info("正在从 %s 加载环境变量", env_path)
    load_dotenv(dotenv_path=env_path, override=True)
else:
    logger.warning(
        "未在 %s 找到 .env 文件，将使用系统环境变量。",
        env_path,
    )

# 检查关键环境变量
if not os.getenv("TAVILY_API_KEY"):
    logger.warning("未设置 TAVILY_API_KEY 环境变量。")

# LLM 走统一工厂，任一已支持的 Key 存在即可启动。
_LLM_KEY_NAMES = (
    "OPENCODE_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "MOONSHOT_API_KEY",
    "XIAOMI_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
)
if not any(os.getenv(name) for name in _LLM_KEY_NAMES):
    logger.warning("未设置任何受支持的 LLM 服务商 Key，LLM 工厂会在首次调用时失败。")

__all__ = ["Graph"]
