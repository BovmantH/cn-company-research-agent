## Context

原项目通过三处硬编码的 LLM 客户端调用模型(`ChatOpenAI` 用 `gpt-5.1`/`gpt-4o`、`ChatGoogleGenerativeAI` 用 `gemini-2.5-flash`),通过 `tavily-python` 客户端在 5 个文件里直接发起搜索请求。所有 prompt 集中在 `backend/prompts.py`,前端无任何 i18n 框架。

要把它本地化为中文版并支持国产模型,需要做两件解耦工作 + 一件文案工作:

1. 把 LLM 调用点收拢到一个工厂,通过 OpenRouter 走任意上游模型
2. 把 Tavily 调用点收拢到一个 `SearchProvider` 接口,为 Phase 2 接 Bocha/AKShare 等留口子
3. 把所有 prompt 与 UI 文案改写为中文

约束:
- LangGraph 工作流、节点拓扑、API 端点契约**保持不变**(降低风险)
- 不引入运行时 i18n 框架(YAGNI,目标用户固定中文)
- 改造完后 `OPENAI_API_KEY` / `GEMINI_API_KEY` 不再是必填,但保留为备选 provider

## Goals / Non-Goals

**Goals:**

- 一份 `.env` 配置即可跑通中文版,**默认走 OpenRouter**
- 模型选择**逐节点可配**(researcher / briefing / editor 可分别绑定不同模型)
- 检索层留出 `SearchProvider` 接口,Phase 2 不需要再动节点代码
- Prompt 与 UI 中文化必须**人工质量**(不能机器翻译过一遍就完事)
- 所有改动可回滚:不删除原有 OpenAI/Gemini 代码路径,只是**默认不走它**

**Non-Goals:**

- 不实现新的 SearchProvider(Bocha/AKShare 等),只搭好接口
- 不做运行时中英切换(只做"中文版")
- 不调整 LangGraph 节点数量或拓扑
- 不改 API 端点 URL 或前后端协议
- 不动 PDF 生成逻辑(`reportlab` 中文字体问题留给后续)
- 不替换 MongoDB 持久化方案

## Decisions

### D1. LLM 网关:OpenRouter + 单一 `LLMFactory`

**决定**:新增 `backend/services/llm_factory.py`,提供 `get_llm(role: str, **overrides) -> BaseChatModel`,内部根据 `role`(`"researcher" | "briefing" | "editor"`)读取环境变量,构造 `langchain_openai.ChatOpenAI`,并把 `base_url` 指向 OpenRouter (`https://openrouter.ai/api/v1`),`api_key` 来自 `OPENROUTER_API_KEY`。

**为什么 OpenRouter 而不是其他**:

| 方案 | 优势 | 劣势 |
|---|---|---|
| **OpenRouter**(选定) | 一个 key 通国内外几百种模型;OpenAI 协议兼容,LangChain 无须改包 | 在中国大陆访问需要科学上网或自建代理(用户已知) |
| LiteLLM | 自托管,可纯本地路由 | 多一层服务,运维成本 |
| 各 provider 直接 SDK | 最直接 | 每加一个模型要改代码,违背 D1 目标 |

**为什么逐节点可配**:不同节点对模型能力需求不同(researcher 要快、briefing 要长上下文、editor 要严谨格式),硬绑一个模型反而浪费。环境变量约定:

```bash
OPENROUTER_API_KEY=sk-or-...
LLM_MODEL_RESEARCHER=deepseek/deepseek-chat        # 默认值,跑得快又便宜
LLM_MODEL_BRIEFING=qwen/qwen-2.5-72b-instruct      # 默认值,长上下文
LLM_MODEL_EDITOR=anthropic/claude-3.5-sonnet       # 默认值,格式严谨
LLM_TEMPERATURE=0
LLM_STREAMING=true
```

用户可在 `.env` 任意覆盖。

**降级路径**:若 `OPENROUTER_API_KEY` 缺失但 `OPENAI_API_KEY` 存在,自动回落到原生 OpenAI(便于已经有 OpenAI key 的用户零配置)。

### D2. 检索抽象层:`SearchProvider` 接口 + Tavily 默认实现

**决定**:新增 `backend/services/search/`,定义抽象基类:

```python
# backend/services/search/__init__.py
class SearchProvider(Protocol):
    async def search(self, query: str, *, max_results: int = 10,
                     time_range: str | None = None,
                     **kwargs) -> list[SearchResult]: ...
    async def crawl(self, url: str, *, max_pages: int = 5,
                    **kwargs) -> list[CrawledPage]: ...
    async def extract(self, urls: list[str], **kwargs) -> list[CrawledPage]: ...
```

并实现 `TavilyProvider`(把现有 5 处 Tavily 调用收拢到这里)。

**为什么不直接换掉 Tavily**:Tavily 对中文确实弱,但替换它属于 Phase 2 的范畴;Phase 1 只做接口抽象,**确保现有功能在重构后仍然 100% 可用**。Phase 2 只要新增 `BochaProvider` 等并改 `.env` 即可切换。

**为什么不上来就做插件系统**:5 个调用点的接口需求很集中(`search` / `crawl` / `extract`),用 Protocol + factory 即可,不需要 entry_points / pluggy 这种重量级方案。

### D3. Prompt 翻译策略:人工重写,保留占位符

**决定**:`backend/prompts.py` 中所有 prompt **全量人工重写为中文**,而非机器翻译后修复。原因:

- prompt 是 LLM 行为的"代码",直译往往保留英文思维(如 "Create a focused, yet comprehensive briefing" → "创建一份聚焦但全面的简报")丢失中文表达习惯
- 中文 prompt 对国内模型(DeepSeek/Qwen)效果显著优于英文 prompt(已有公开 benchmark 验证)
- 模板占位符(`{company}`、`{industry}`、`{hq_location}`)**必须保留原变量名**,避免改动调用方代码

**质量门槛**:每条 prompt 改写后,人工检查三件事:
1. 占位符未丢失或重命名
2. 输出格式指令(`### 标题`、`* 列表项`)与原版一致(下游解析依赖)
3. "Never mention 'no information found'" 这类 negative instruction 完整保留

### D4. 前端文案:硬替换,不引入 i18n

**决定**:`ui/src/components/*.tsx` 中的英文字符串**直接替换为中文字面量**,不引入 `i18next`。

**为什么**:

- 目标用户单一(中文),引入 i18n 是 over-engineering
- 9 个组件、约 40-60 处文案,工作量小
- 引入 i18n 反而需要新增构建依赖、配置加载、命名空间管理

**约定**:中文文案就地写在 JSX 里,不抽公共字典。如果未来真要做多语言,再做迁移。

### D5. 配置与文档

**决定**:

- `.env.example` 重写为中文注释 + 新变量
- `requirements.txt` 中 `langchain-google-genai` 标记为 optional(代码中改为 try-import,缺失时不报错)
- `README.md` 用中文重写,**保留 LICENSE 文件不变**,在 README 头部加"基于 guy-hartstein/company-research-agent (MIT)"块
- 删除 `README.es/fr/jp/kr/zh.md`(我们就是中文版,没必要再保留多语言 README;如果想留,只保留 `README.en.md` 作为英文备份)

## Risks / Trade-offs

| Risk | Mitigation |
|---|---|
| OpenRouter 在国内访问受限,用户跑不起来 | `.env.example` 给出"OpenRouter 国内访问"配置示例(`HTTPS_PROXY`);保留 OpenAI 直连降级路径 |
| `LLMFactory` 抽象后流式输出(streaming)行为可能与原版不一致 | 新增端到端测试,在 researcher/editor 节点验证 streaming 仍能逐 token 推送到前端 |
| 中文 prompt 改写后,LLM 输出格式偏离原解析逻辑(下游 `briefing.py` / `editor.py` 依赖固定 markdown 结构) | 改写后跑一次完整流程,检查 `### Core Product/Service` 这类标题是否仍然出现;必要时在 prompt 末尾加"严格输出以下中文标题:..." |
| 替换 Tavily 调用为 `SearchProvider.search()` 时,参数语义错位(如 `topic="news"`、`time_range="month"` 的 Tavily 专有参数) | 在 `TavilyProvider.search` 内部处理这些 kwargs,接口层只暴露通用参数;Tavily 专有参数走 `**kwargs` 透传 |
| 前端 `Header.tsx` 等组件中 logo / 例子公司名(如 "Apple")不再合适 | 一并替换为中国公司示例(腾讯、字节、宁德时代等);评估一遍硬编码图片 / icon 是否需要换 |
| README 重写后丢失原作者贡献感 | README 顶部 + LICENSE 文件双重保留出处;`git log` 首条 commit 已注明 |
| Phase 1 跑通后 Phase 2 才发现 SearchProvider 接口不够用 | 接口设计参考 Tavily / Bocha / Serper 公开 API 取并集,先实现并把 Tavily 跑通,再用纸面方式校验 Bocha 适配可行性(此校验作为本期 Open Question 留给 Phase 2) |

## Migration Plan

新仓库刚初始化,无在线流量,迁移即"按 tasks.md 顺序实施",但内部分阶段保证每个 commit 都能跑:

1. **Stage 1 — 抽象层落地**:`LLMFactory` + `SearchProvider` 接口 + `TavilyProvider`,**不改默认行为**(默认仍走 OpenAI/Tavily,因为 env vars 未配)。完成后跑原版功能验证。
2. **Stage 2 — 切换默认 provider**:`.env.example` 与 `LLMFactory` 默认指向 OpenRouter。完成后用一个国产模型跑通端到端。
3. **Stage 3 — 文案中文化**:Prompt → API 响应 → 前端文案 → README,逐文件提交。
4. **Stage 4 — 验收**:用"宁德时代"做端到端 smoke test,产物报告全中文,无英文残留。

回滚策略:每个 stage 一个或多个 commit,回滚就是 `git revert`;LLMFactory 的降级路径(OpenAI fallback)即天然回滚。

## Open Questions

- **PDF 中文字体**:`reportlab` 默认无中文字体,生成的 PDF 中文会变成方框。是否本期要解决?**建议留给 Phase 2**(可在 README 注明已知问题),否则要嵌字体文件,License 也要留意。
- **Bocha AI / 智谱搜索的接口形状**:Phase 2 才会接,但接口形状是否完全能套进 `SearchProvider`?**建议在 Phase 1 完工时,纸面验证一次**(读各 provider 的 API 文档,确认参数能映射),不写代码。
- **OpenRouter 模型默认值**:目前默认 `deepseek-chat` / `qwen-2.5-72b` / `claude-3.5-sonnet`,是否要换成成本更低的组合?**建议跑一次 cost benchmark 后再定**,本期先用上述默认。
