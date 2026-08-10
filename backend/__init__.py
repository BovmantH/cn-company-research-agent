"""Backend package for cn-company-research(中文公司调研 agent)。

LLM 调用统一通过 ``backend.services.llm_factory.get_llm`` 走 OpenRouter,
检索调用统一通过 ``backend.services.search.get_search_provider`` 走
``SearchProvider`` 接口(默认 Tavily)。本模块仅做 ``.env`` 加载与启动告警。
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from .graph import Graph

# Set up logging
logger = logging.getLogger(__name__)

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    logger.info(f"Loading environment variables from {env_path}")
    load_dotenv(dotenv_path=env_path, override=True)
else:
    logger.warning(
        f".env file not found at {env_path}. Using system environment variables."
    )

# Check for critical environment variables
if not os.getenv("TAVILY_API_KEY"):
    logger.warning("TAVILY_API_KEY environment variable is not set.")

# LLM 走统一工厂,任一 key 存在即可启动;Gemini 不再为强依赖
if not os.getenv("OPENROUTER_API_KEY") and not os.getenv("OPENAI_API_KEY"):
    logger.warning(
        "Neither OPENROUTER_API_KEY nor OPENAI_API_KEY is set; "
        "LLMFactory will fail at first call."
    )

__all__ = ["Graph"]
