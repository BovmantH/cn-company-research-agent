"""区分可访问的来源地址和仅用于去重的资源标识。"""

from urllib.parse import unquote_plus, urlsplit

# 只识别明确的广告/分析追踪字段；source、id、token 等可能决定业务资源。
TRACKING_QUERY_PARAMETERS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_source_platform",
        "utm_creative_format",
        "utm_marketing_tactic",
        "gclid",
        "dclid",
        "fbclid",
        "msclkid",
    }
)


def normalize_source_url(url: str) -> str:
    """补全协议、移除片段；不改写签名查询、编码、参数顺序或路径。"""
    if not url:
        return ""
    candidate = url.strip()
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        return parsed._replace(fragment="").geturl()
    except ValueError:
        return ""


def source_url_identity(url: str) -> str:
    """仅在去重键中忽略已知追踪字段，绝不把此键当正文或引用地址。"""
    normalized = normalize_source_url(url)
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    parts = [
        part
        for part in parsed.query.split("&")
        if unquote_plus(part.partition("=")[0]).lower() not in TRACKING_QUERY_PARAMETERS
    ]
    return parsed._replace(query="&".join(parts)).geturl()
