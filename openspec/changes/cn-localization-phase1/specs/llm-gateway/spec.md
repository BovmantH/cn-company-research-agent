## ADDED Requirements

### Requirement: 统一的 LLM 工厂入口

系统 SHALL 提供一个 `LLMFactory.get_llm(role: str, **overrides)` 函数,作为后端所有 LLM 调用的唯一入口。`role` 参数取值为 `"researcher"`、`"briefing"`、`"editor"` 之一,工厂根据 `role` 与环境变量构造对应的 `BaseChatModel` 实例并返回。

#### Scenario: 通过 OpenRouter 获取 researcher 模型

- **WHEN** 环境变量 `OPENROUTER_API_KEY` 已设置且 `LLM_MODEL_RESEARCHER=deepseek/deepseek-chat`
- **THEN** `get_llm("researcher")` 返回的 `ChatOpenAI` 实例 `base_url` 等于 `https://openrouter.ai/api/v1`,`model` 等于 `deepseek/deepseek-chat`,`api_key` 等于 `OPENROUTER_API_KEY` 的值

#### Scenario: 不同角色使用独立模型

- **WHEN** `.env` 中 `LLM_MODEL_RESEARCHER=deepseek/deepseek-chat`、`LLM_MODEL_BRIEFING=qwen/qwen-2.5-72b-instruct`、`LLM_MODEL_EDITOR=anthropic/claude-3.5-sonnet`
- **THEN** 三次 `get_llm` 调用返回的 model 字段分别为这三个值,互不干扰

#### Scenario: 调用方通过 overrides 临时覆盖参数

- **WHEN** 调用方传入 `get_llm("researcher", temperature=0.7, streaming=False)`
- **THEN** 返回的 LLM 实例 `temperature` 为 0.7、`streaming` 为 False,其余参数仍按 `role` 默认值

### Requirement: OpenRouter 缺失时降级到 OpenAI

系统 SHALL 在 `OPENROUTER_API_KEY` 未设置但 `OPENAI_API_KEY` 存在时,自动回落到原生 OpenAI 端点(`https://api.openai.com/v1`),并使用 `LLM_MODEL_RESEARCHER` 等环境变量指定的 model 字符串(去掉 OpenRouter 的 vendor 前缀)。

#### Scenario: 仅配置 OpenAI key 时不应崩溃

- **WHEN** `.env` 仅有 `OPENAI_API_KEY=sk-...`,且 `LLM_MODEL_RESEARCHER` 未设置或为 `gpt-4o-mini`
- **THEN** `get_llm("researcher")` 返回的 `ChatOpenAI` 调用真实 OpenAI 端点,不抛异常

#### Scenario: 两个 key 都缺失时给出明确错误

- **WHEN** `OPENROUTER_API_KEY` 与 `OPENAI_API_KEY` 都未设置
- **THEN** `get_llm(...)` 抛出 `RuntimeError`,异常信息中包含"未配置 OPENROUTER_API_KEY 或 OPENAI_API_KEY"

### Requirement: 流式输出语义保持

系统 SHALL 在工厂构造的 LLM 实例上保持 `streaming=True` 默认开启,确保前端 SSE/WebSocket 通道仍能逐 token 接收输出。

#### Scenario: researcher 节点流式行为不变

- **WHEN** `researchers/base.py` 通过 `LLMFactory.get_llm("researcher")` 替换原 `ChatOpenAI` 直接构造
- **THEN** 调用 `llm.astream(messages)` 仍能产出 `AsyncIterator[BaseMessageChunk]`,前端在 `/research/{job_id}/stream` 端点收到的事件流时间戳间隔无显著变化(±20% 以内)

### Requirement: 默认模型不强制锁定

系统 SHALL 提供合理默认模型,但**用户可通过 `.env` 完全覆盖**,工厂代码中 SHALL NOT 出现"如果用户没配某个模型就硬编码使用某厂商"的逻辑。

#### Scenario: 用户用纯本地 vLLM 端点

- **WHEN** 用户配置 `OPENROUTER_API_KEY=ignored`、`OPENAI_API_BASE=http://localhost:8000/v1` 与 `LLM_MODEL_RESEARCHER=local-model`
- **THEN** 工厂应允许此种配置生效(实现可通过额外环境变量 `LLM_BASE_URL` 覆盖默认 base_url)
