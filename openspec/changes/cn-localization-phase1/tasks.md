## 1. 抽象层基础设施(后端)

- [x] 1.1 创建 `backend/services/__init__.py`(已存在则跳过),确认 `services` 模块可导入
- [x] 1.2 创建 `backend/services/llm_factory.py`,定义 `get_llm(role: str, **overrides) -> BaseChatModel`,支持 `OPENROUTER_API_KEY` + `LLM_MODEL_*` 环境变量,实现 OpenAI fallback 与缺 key 时的明确报错
- [x] 1.3 在 `tests/services/test_llm_factory.py` 写单元测试覆盖:OpenRouter 路径、OpenAI 降级、缺 key 报错、role 隔离、overrides 覆盖
- [x] 1.4 创建 `backend/services/search/__init__.py`,定义 `SearchProvider` Protocol、`SearchResult`、`CrawledPage` dataclass、`get_search_provider()` 工厂
- [x] 1.5 创建 `backend/services/search/tavily_provider.py`,实现 `TavilyProvider`,封装现 Tavily 客户端的 search/crawl/extract 三类调用
- [x] 1.6 在 `tests/services/search/test_tavily_provider.py` 用 `respx` 或 `pytest-mock` mock Tavily HTTP 响应,验证返回值映射正确(包括 `score`、`raw` 字段)

## 2. LLM 工厂接入现有节点

- [x] 2.1 修改 `backend/nodes/researchers/base.py`,把 `ChatOpenAI(model="gpt-5.1", ...)` 替换为 `LLMFactory.get_llm("researcher")`,删除直接 import
- [x] 2.2 修改 `backend/nodes/briefing.py`,把 `ChatGoogleGenerativeAI(model="gemini-2.5-flash", ...)` 替换为 `get_llm("briefing")`
- [x] 2.3 修改 `backend/nodes/editor.py`,把 `ChatOpenAI(model="gpt-4o", ...)` 替换为 `get_llm("editor")`,保持 streaming 行为
- [x] 2.4 用 `pytest-asyncio` 跑一次集成测试:在 mock LLM 下,3 个节点能成功初始化、`astream` 正常产出 chunk
- [x] 2.5 把 `langchain-google-genai` 改为 try-import,缺失依赖时不阻塞启动(`requirements.txt` 改为 optional 注释)

## 3. SearchProvider 接入现有节点

- [x] 3.1 修改 `backend/nodes/grounding.py`,改为通过 `get_search_provider()` 获取 provider,所有 Tavily 调用走接口
- [x] 3.2 修改 `backend/nodes/enricher.py`,移除直接 `tavily` import,改走 provider
- [x] 3.3 修改 `backend/nodes/curator.py`,移除直接 `tavily` import,改走 provider
- [x] 3.4 修改 `backend/nodes/researchers/base.py`,把其中 Tavily 搜索调用改为 provider(注意此文件第 1 步已替换 LLM,这里只动 search 相关行)
- [x] 3.5 修改 `backend/utils/references.py`,Tavily 调用改走 provider
- [x] 3.6 在 `backend/__init__.py` 删除遗留 `tavily` import(若存在)
- [x] 3.7 静态校验:`grep -r "from tavily\|AsyncTavilyClient" backend/nodes backend/utils` 应输出 0 行

## 4. 配置与依赖

- [x] 4.1 重写 `.env.example`,加中文注释,新增 `OPENROUTER_API_KEY`、`LLM_MODEL_RESEARCHER`、`LLM_MODEL_BRIEFING`、`LLM_MODEL_EDITOR`、`LLM_TEMPERATURE`、`LLM_STREAMING`、`LLM_BASE_URL`、`SEARCH_PROVIDER` 等键,标注哪些必填、哪些可选
- [x] 4.2 整理 `requirements.txt`:`langchain-google-genai` 移到注释段(或 `requirements-optional.txt`),保留 `langchain-openai`、`tavily-python`、`langchain`、`langgraph` 等核心依赖
- [x] 4.3 在 `application.py` 启动时读取 `.env` 后,对 `OPENROUTER_API_KEY`/`OPENAI_API_KEY` 至少一个存在做启动校验,缺失则打印中文警告并退出

## 5. Prompt 中文化

- [ ] 5.1 重写 `backend/prompts.py` 中 `COMPANY_BRIEFING_PROMPT`、`INDUSTRY_BRIEFING_PROMPT` 为中文(占位符与小标题保持一致映射:`### Core Product/Service` → `### 核心产品/服务` 等)
- [ ] 5.2 重写 `backend/prompts.py` 中 financial / news / company / industry 各 researcher 的 query 生成 prompt 与 analyzer prompt 为中文
- [ ] 5.3 重写 curator / enricher / editor / collector 相关 prompt 为中文
- [ ] 5.4 同步修改 `briefing.py`、`editor.py` 等下游节点中**依赖标题字符串解析**的代码(把 `"### Core Product/Service"` 换成 `"### 核心产品/服务"` 等)
- [ ] 5.5 用一家中国公司(建议「宁德时代」)跑一次端到端,人工核查输出 4 份 briefing(company/industry/news/financial)是否中文、格式是否对齐
- [ ] 5.6 commit 当前进度,留好回退点

## 6. 前端文案中文化

- [ ] 6.1 重写 `ui/src/components/Header.tsx` 文案
- [ ] 6.2 重写 `ui/src/components/ResearchForm.tsx` 文案(placeholder × 4、按钮、label)
- [ ] 6.3 重写 `ui/src/components/LocationInput.tsx` 文案(`"City, Country"` → 「城市,国家」或更适合中国公司的「城市」)
- [ ] 6.4 重写 `ui/src/components/ExamplePopup.tsx` 文案与示例公司列表(替换为腾讯/字节/宁德时代/比亚迪等)
- [ ] 6.5 重写 `ui/src/components/ResearchStatus.tsx`、`ResearchReport.tsx`、`ResearchBriefings.tsx`、`ResearchQueries.tsx`、`CurationExtraction.tsx` 中的英文文案
- [ ] 6.6 全局搜索 `ui/src` 残余英文(用正则 `>[A-Z][a-z]{3,}` 与 `placeholder="[A-Z]`),确认没有遗漏
- [ ] 6.7 启动前端,目视检查每个交互页面无英文残留(404、错误提示、loading 等也要看)

## 7. API 响应文案中文化

- [ ] 7.1 修改 `application.py` 中所有面向用户的 `message` 字段、HTTP error detail、日志提示(保留日志的英文 logger name 但中文化对外消息)
- [ ] 7.2 用 `curl` 验证 POST `/research` 返回中文 message;构造一个错误请求验证错误消息也是中文

## 8. README 与文档

- [x] 8.1 重写 `README.md` 为中文版,保留架构图、安装步骤、env 变量说明,顶部加 MIT 致谢与原仓库链接
- [x] 8.2 删除 `README.es.md`、`README.fr.md`、`README.jp.md`、`README.kr.md`、`README.zh.md`(原中文 README 已被新版主 README 取代)
- [x] 8.3 保留 `LICENSE` 不动;检查 `git diff --stat` 确认 LICENSE 字节数与原版一致
- [x] 8.4 在 README 加一个「与原版差异」表格,简述:LLM 走 OpenRouter、检索抽象、prompt 中文化、UI 中文化

## 9. 端到端验收

- [ ] 9.1 用「宁德时代」做完整一次调研流程,产物报告全中文,无英文残留(报告主体、4 份 briefing、引用列表)
- [ ] 9.2 用「DeepInfra 国产 model」与「OpenAI fallback」两种配置各跑一次,确认 LLMFactory 双路径都正常
- [ ] 9.3 静态再检:`grep -r "tavily\|AsyncTavilyClient" backend/nodes backend/utils` 应仅在 `tavily_provider.py` 中出现
- [ ] 9.4 在 README 顶部加一段「Phase 1 完成度自检」截图或文字记录(可选,展示 Phase 1 落地结果)
- [ ] 9.5 创建一个 git tag `v0.1.0-phase1`,作为 Phase 2 的基线
- [ ] 9.6 在 openspec 仓库执行 `openspec archive cn-localization-phase1`,把本次 change 归档,specs/ 沉淀为基线

## 10. Phase 2 准备(纸面)

- [ ] 10.1 阅读 Bocha AI、智谱搜索、Serper.dev 三家 API 文档,在 `docs/phase2-search-providers.md` 列出参数映射表,验证 SearchProvider 接口能否兼容(如不能,记录需要扩展的接口字段)
- [ ] 10.2 阅读 AKShare、巨潮资讯网 API,起草 Phase 2 的新 change proposal `cn-domestic-data-sources`(暂不实施)
