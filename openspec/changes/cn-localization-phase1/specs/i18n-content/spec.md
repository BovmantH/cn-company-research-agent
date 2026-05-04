## ADDED Requirements

### Requirement: backend/prompts.py 全量中文化

系统 SHALL 将 `backend/prompts.py` 中所有 prompt 常量改写为中文,且**保留原变量名、占位符名、输出格式标记**(如 `### 标题`、`* 列表项`)。

#### Scenario: 占位符完整保留

- **WHEN** 原 prompt 包含 `{company}`、`{industry}`、`{hq_location}` 等占位符
- **THEN** 中文化后的 prompt 中这些占位符 SHALL 原样存在,数量与名字一一对应

#### Scenario: 输出标题与下游解析对齐

- **WHEN** 原 prompt 要求模型输出 `### Core Product/Service`、`### Leadership Team` 等英文小标题
- **THEN** 中文化后 prompt 改为要求 `### 核心产品/服务`、`### 领导团队`,且 `briefing.py` / `editor.py` 中相应解析逻辑同步更新到中文标题

#### Scenario: 否定指令保留

- **WHEN** 原 prompt 包含 `Never mention "no information found"` 这类否定指令
- **THEN** 中文化后 prompt SHALL 包含等效中文否定指令(如「不得提及"未找到信息"或"暂无数据"」)

### Requirement: 前端 UI 文案中文化

系统 SHALL 将 `ui/src/components/` 下 9 个组件中的英文硬编码字符串(包括 `placeholder`、按钮文字、状态提示、占位文本等)替换为中文,且不引入 i18n 框架。

#### Scenario: 表单 placeholder 中文化

- **WHEN** 用户访问首页 `/`
- **THEN** ResearchForm 公司名输入框 placeholder 显示「输入公司名称」、网址输入框显示 `example.com`(此项保留英文)、行业输入框显示「如:互联网、新能源」、提交按钮文字显示「开始调研」

#### Scenario: 状态文案中文化

- **WHEN** 调研运行中,前端展示进度
- **THEN** ResearchStatus / ResearchReport 等组件中显示的状态(原英文如 "Generating report...")替换为中文(如「正在生成报告……」)

#### Scenario: 示例公司本地化

- **WHEN** 用户点击 ExamplePopup
- **THEN** 弹窗中默认示例公司从原版的英文公司(如 Apple、Stripe)替换为中文用户熟悉的示例(如腾讯、字节跳动、宁德时代)

### Requirement: API 响应消息中文化

系统 SHALL 将 `application.py` 中所有用户可见的 API 响应消息字段改写为中文。

#### Scenario: 启动调研接口返回中文消息

- **WHEN** 客户端 POST `/research` 成功创建任务
- **THEN** 响应 JSON 中 `message` 字段为「调研已启动,请连接 /research/{job_id}/stream 接收进度」(或同等中文表述)

### Requirement: README 中文化与 MIT 致谢

系统 SHALL 将 `README.md` 重写为中文版,并在显眼位置(README 顶部 quote block 或第一段)注明本仓库基于 `guy-hartstein/company-research-agent` (MIT License) 改造。

#### Scenario: README 顶部出现来源声明

- **WHEN** 任意人在 GitHub 浏览本仓库 README
- **THEN** 在不滚动屏幕、首屏可见的位置出现一段 markdown 引用,内容包含原仓库链接、原作者名、"MIT" 字样、本项目相对原版的差异化简述

#### Scenario: LICENSE 文件不变

- **WHEN** 比较本仓库 `LICENSE` 文件与原仓库 `LICENSE` 文件
- **THEN** 两份文件的版权声明行(`Copyright (c) ... Guy Hartstein`)完全一致,本项目不修改原 LICENSE 内容

### Requirement: 不引入运行时 i18n 框架

系统 SHALL NOT 在前端引入 `i18next`、`react-intl` 等运行时多语言切换框架。中文化通过直接替换字面量完成。

#### Scenario: 依赖检查

- **WHEN** 在 `ui/package.json` 中查找
- **THEN** dependencies 与 devDependencies 中均不出现 `i18next`、`react-i18next`、`react-intl`、`@formatjs/*` 等包
