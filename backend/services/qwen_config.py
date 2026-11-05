"""百炼业务空间只用于构造已知官方域名。"""

import re

from .provider_registry import VENDOR_REGISTRY


def normalize_qwen_workspace_id(value: str | None) -> str | None:
    normalized = value.strip() if value else None
    if normalized and not re.fullmatch(r"[A-Za-z0-9-]{1,64}", normalized):
        raise ValueError("百炼业务空间 ID 格式不正确")
    return normalized or None


def qwen_inference_base_url(value: str | None) -> str:
    workspace = normalize_qwen_workspace_id(value)
    return (
        f"https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        if workspace
        else VENDOR_REGISTRY["qwen"].base_url
    )
