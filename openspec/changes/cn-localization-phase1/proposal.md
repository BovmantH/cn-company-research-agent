## Why

原项目 `guy-hartstein/company-research-agent` 是一个面向英文用户、调研欧美公司的多 agent 工具,但中文用户在调研中国公司时存在三个明显短板:

1. **语言不通**:Prompt、UI、报告全部英文,不符合中文用户阅读习惯
2. **模型不灵活**:硬编码了 OpenAI / Gemini,在中国大陆访问受限,且对国产模型(DeepSeek、Qwen 等)毫无支持
3. **未来需要本土数据源**:Tavily 对中文站点覆盖一般,后续接 AKShare/巨潮/企查查 时需要可扩展的检索抽象

本 Phase 1 解决前两个问题(语言 + LLM 网关),并为第三个问题搭好检索抽象的"插座",留给 Phase 2(C 档)实现。

## What Changes

- 引入 **OpenRouter** 作为统一 LLM 网关,通过 `langchain-openai` 兼容接口调用,**同时支持国外(GPT/Claude/Gemini)与国内(DeepSeek/Qwen/Kimi/智谱)模型**,模型可通过环境变量逐节点切换
- **BREAKING**:`backend/nodes/researchers/base.py`、`briefing.py`、`editor.py` 中硬编码的 `ChatOpenAI` / `ChatGoogleGenerativeAI` 改为统一的 `LLMFactory` 工厂方法
- 中文化 `backend/prompts.py` 中所有 prompt(全文重写,而非机器翻译)
- 中文化前端 9 个组件(`ui/src/components/*.tsx`)的硬编码英文文案
- 中文化 `application.py` 中的 API 响应消息
- 重写 `README.md` 为中文,在显眼位置标注"基于 guy-hartstein/company-research-agent (MIT)"
- 引入**检索抽象层**(`SearchProvider` 接口),Tavily 实现作为默认 provider,**为 Phase 2 接入 Bocha AI / 国内数据源预留扩展点**(本期不实现新 provider)
- 更新 `.env.example`、`requirements.txt`,新增 `OPENROUTER_API_KEY` 等配置项,移除强制依赖 `OPENAI_API_KEY`/`GEMINI_API_KEY`

## Capabilities

### New Capabilities

- `llm-gateway`: 统一的 LLM 调用入口,封装模型选择、provider 切换、降级回退、流式输出等横切关注点
- `search-adapter`: 检索层抽象接口(`SearchProvider`),解耦上层节点与具体搜索引擎实现,支持未来按需新增 provider
- `i18n-content`: 全量中文化的 prompt 与 UI 文案管理(本期不引入 i18next 等动态切换框架,直接全量替换)

### Modified Capabilities

- (无 —— openspec/specs/ 目前为空,此次为首批 spec)

## Impact

### 范围(In Scope)

- 后端 LLM 调用统一走 OpenRouter,通过工厂可切换具体模型
- `backend/prompts.py` 全量中文化,保留原变量名与 `{...}` 占位符不变
- 前端 9 个组件的英文硬编码替换为中文,**不引入 i18n 框架**(YAGNI)
- README 中文化 + MIT 致谢
- 检索抽象层接口与 Tavily 默认实现(适配器模式)

### 范围外(Out of Scope,留给 Phase 2)

- 新增 Bocha AI / Serper / 智谱搜索等具体 provider 实现
- AKShare / 巨潮资讯网 / 企查查 / 天眼查 等专用数据源 node
- 引入 i18next 做运行时中英切换
- 调整 LangGraph 节点拓扑(本期保持原工作流不变)
- 中国公司调研维度调整(如增加"高管背景"、"股权穿透"等)

### 受影响文件清单

**后端**
- `backend/prompts.py`(全量重写为中文)
- `backend/nodes/researchers/base.py`(LLM 工厂化)
- `backend/nodes/briefing.py`(LLM 工厂化)
- `backend/nodes/editor.py`(LLM 工厂化)
- `backend/services/llm_factory.py`(**新增**)
- `backend/services/search/__init__.py`(**新增**,SearchProvider 接口)
- `backend/services/search/tavily_provider.py`(**新增**,把现有 Tavily 调用收拢)
- `backend/nodes/grounding.py`、`enricher.py`、`curator.py`、`utils/references.py`(改为通过 SearchProvider 调用)
- `application.py`(响应消息中文化)

**前端**
- `ui/src/components/Header.tsx`、`ResearchForm.tsx`、`ResearchReport.tsx`、`ResearchBriefings.tsx`、`ResearchQueries.tsx`、`ResearchStatus.tsx`、`CurationExtraction.tsx`、`LocationInput.tsx`、`ExamplePopup.tsx`(英文文案 → 中文)

**配置与文档**
- `.env.example`(新增 `OPENROUTER_API_KEY`、`LLM_MODEL_RESEARCHER` 等)
- `requirements.txt`(可能需要调整 langchain-openai 版本,移除 langchain-google-genai 强依赖)
- `README.md`(全量重写为中文)
- `LICENSE`(保持原 MIT 不动)

### API / 依赖影响

- **新增依赖**:无(复用 `langchain-openai` 调 OpenRouter)
- **可移除依赖**:`langchain-google-genai`(若完全切走 Gemini)、`tavily-python`(本期保留作为默认 provider)
- **环境变量变化**:`OPENAI_API_KEY` / `GEMINI_API_KEY` 变为可选,新增 `OPENROUTER_API_KEY` 与每节点的模型选择变量
- **API 端点**:不变(保持 `/research`、`/research/{job_id}/stream` 等)
- **数据契约**:`InputState` 不变,前后端协议不变
