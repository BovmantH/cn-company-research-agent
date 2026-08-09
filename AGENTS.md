# AGENTS.md

本文件适用于整个仓库。所有自动化 Agent 在读取、修改、测试或提交代码前必须遵守。

## 项目定位

这是一个面向中国公司的开源调研 Web 服务：FastAPI + LangGraph 后端、React/Vite 前端。基础调研走 Web `SearchProvider`；工商司法等付费结构化事实走独立的 Company Intelligence 模块。

## 工作方式

- 采用“小步快走”：每次只完成一个可独立理解、可独立测试、可安全回滚的垂直切片。
- 一个切片验证通过后立即提交；不要把无关重构、依赖升级、格式化或文档整理混进同一提交。
- 提交前检查 `git diff --check`、相关测试和 `git status`，只暂存本切片文件。
- 多 Agent 只拆分互不依赖或只读任务。共享工作区中由主 Agent 统一整合和提交，子 Agent 未经明确安排不得提交。
- 发现用户已有未提交改动时必须保留；不要重置、覆盖或顺手整理。
- 不使用 Superpowers 技能或工作流。本项目使用 Codex 原生能力及明确启用的其他技能。

## 本地计划与 Git 边界

- `openspec/`、`docs/superpowers/specs/` 是本地设计/计划资料，故意不进入版本控制。
- 不得强制添加、提交或推送上述目录。若代码实现需要引用设计结论，在已跟踪的代码、测试或 README 中只写必要契约，不复制整份本地设计稿。
- 不创建包含真实 Key、Cookie、Token、账户余额或上游原始敏感响应的文件。

## 架构边界

- `backend/services/search/` 只负责网页搜索、抓取和正文提取，不承载工商司法结构化数据。
- `backend/services/company_intelligence/` 负责主体识别、预算准入、Provider 调用、Evidence 标准化、缓存和审计边界。
- 付费 Provider 调用必须发生在预算预留和幂等检查之后；LLM 不得自由选择或循环调用付费工具。
- 工商登记、案号、金额、日期、法院和当事人角色必须确定性渲染，不能交给 LLM 改写。
- `succeeded_empty`、`failed`、`partial`、`not_requested`、`unavailable` 和 `budget_blocked` 是不同业务状态，不得互相替代。
- 专业数据分支失败不得阻断基础 Web 报告。

## 安全与合规

- 企查查采用部署实例 BYOK：`QCC_API_KEY` 只能存在于服务端环境变量或 Secret 中。
- 默认关闭企查查能力；只有部署者显式配置 Key、持久化账本、签名密钥和正数预算后才能对外启用。
- 未经用户明确授权，不执行会消耗付费 API 积分的真实 Smoke/E2E 调用。
- 不抓取需要登录的爱企查、企查查网页或中国执行信息公开网；不保存第三方 Cookie，不绕过验证码、限流或反自动化措施。
- API/SSE/日志不得返回密钥、Authorization 头、上游账户信息或未经脱敏的错误正文。

## 验证命令

后端相关改动至少运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

前端相关改动至少运行：

```powershell
Set-Location ui
npm run build
```

若修改 OpenSpec 本地变更，额外运行：

```powershell
openspec validate <change-id> --strict
```

## Agent skills

### Issue tracker

需求与可发布规格默认使用当前 GitHub 仓库的 Issues。见 `docs/agents/issue-tracker.md`。

### Triage labels

使用 Matt 工程技能的五类标准 triage 标签。见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库采用单一上下文布局：根目录 `CONTEXT.md` 与 `docs/adr/`（按需创建）。见 `docs/agents/domain.md`。
