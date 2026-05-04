## ADDED Requirements

### Requirement: SearchProvider 抽象接口

系统 SHALL 定义一个 `SearchProvider` Protocol(在 `backend/services/search/__init__.py`),包含三个异步方法:`search`、`crawl`、`extract`。所有上层节点 SHALL 通过该接口而非直接调用 `tavily_python` 客户端来获取检索结果。

#### Scenario: 接口签名稳定

- **WHEN** 任意 provider 实现该接口
- **THEN** 必须实现 `async def search(self, query: str, *, max_results: int = 10, time_range: str | None = None, **kwargs) -> list[SearchResult]`、`async def crawl(self, url: str, *, max_pages: int = 5, **kwargs) -> list[CrawledPage]`、`async def extract(self, urls: list[str], **kwargs) -> list[CrawledPage]` 三个方法,且参数名与默认值一致

### Requirement: 搜索结果统一数据结构

系统 SHALL 定义 `SearchResult` 与 `CrawledPage` 数据类(`@dataclass` 或 `pydantic.BaseModel`),provider 必须将原始返回值映射为该结构后再返回上层。

#### Scenario: SearchResult 必备字段

- **WHEN** 任意 provider 返回 `list[SearchResult]`
- **THEN** 每个 `SearchResult` 实例 SHALL 至少包含字段:`url: str`、`title: str`、`content: str`、`score: float`(0-1,若 provider 不提供则填 0.0)、`published_date: str | None`

#### Scenario: 未知字段以 raw 字典保留

- **WHEN** 上游 provider 返回 SearchResult 标准字段以外的元数据(如 Tavily 的 `raw_content`)
- **THEN** 这些字段 SHALL 透明保留在 `SearchResult.raw: dict[str, Any]` 中,不抛弃

### Requirement: TavilyProvider 默认实现

系统 SHALL 提供 `TavilyProvider`(在 `backend/services/search/tavily_provider.py`),作为 `SearchProvider` 的默认实现,封装现有所有 `AsyncTavilyClient` 调用。

#### Scenario: 替换前后行为等价

- **WHEN** 节点(`grounding`、`enricher`、`curator`、`researcher.base`)从直接调用 `AsyncTavilyClient.search(...)` 改为调用 `provider.search(...)`
- **THEN** 在相同输入下,返回的 SearchResult 数量与每条结果的 url 应与原版完全一致(可能差一点 score 浮点精度)

#### Scenario: Tavily 专有参数透传

- **WHEN** 调用 `tavily_provider.search(query, topic="news", time_range="month", search_depth="advanced")`
- **THEN** Tavily 客户端接收到的请求 SHALL 包含 `topic="news"`、`time_range="month"`、`search_depth="advanced"`(通过 `**kwargs` 透传)

### Requirement: provider 通过工厂选择

系统 SHALL 提供 `get_search_provider() -> SearchProvider` 工厂函数,根据环境变量 `SEARCH_PROVIDER`(默认值 `"tavily"`)返回对应实例。

#### Scenario: 默认返回 Tavily

- **WHEN** 环境变量 `SEARCH_PROVIDER` 未设置
- **THEN** `get_search_provider()` 返回 `TavilyProvider` 实例

#### Scenario: 未知 provider 给出明确错误

- **WHEN** `SEARCH_PROVIDER=unknown_xyz`
- **THEN** `get_search_provider()` 抛出 `ValueError`,信息中列出当前已注册的 provider 名

### Requirement: 节点不再直接 import tavily

系统 SHALL 在重构完成后,使 `backend/nodes/` 目录下任何文件**不再 import `tavily` 或 `AsyncTavilyClient`**。所有检索调用通过 `SearchProvider` 接口完成。

#### Scenario: 静态检查无 tavily 残留

- **WHEN** 在 `backend/nodes/` 目录下执行 `grep -r "from tavily" .` 或 `grep -r "AsyncTavilyClient" .`
- **THEN** 命中数量为 0(`backend/services/search/tavily_provider.py` 是唯一允许出现 tavily import 的位置)
