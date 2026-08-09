# Issue tracker: GitHub

本仓库的需求、规格和任务默认存放在 GitHub Issues，使用 `gh` CLI 操作，并始终明确目标仓库为 `BovmantH/cn-company-research-agent`，避免误操作 `upstream`。

## 约定

- 创建：`gh issue create --repo BovmantH/cn-company-research-agent --title "..." --body "..."`
- 读取：`gh issue view <number> --repo BovmantH/cn-company-research-agent --comments`
- 列表：`gh issue list --repo BovmantH/cn-company-research-agent --state open --json number,title,body,labels,comments`
- 评论：`gh issue comment <number> --repo BovmantH/cn-company-research-agent --body "..."`
- 标签：`gh issue edit <number> --repo BovmantH/cn-company-research-agent --add-label "..."`
- 关闭：`gh issue close <number> --repo BovmantH/cn-company-research-agent --comment "..."`

多行正文优先使用临时 Markdown 文件或 PowerShell here-string，避免复杂转义破坏内容。

## Pull requests as a triage surface

**PRs as a request surface: no.** 外部 PR 默认不自动进入需求 triage 队列。

## 技能术语映射

- “publish to the issue tracker”表示创建 GitHub Issue。
- “fetch the relevant ticket”表示读取对应 Issue 及评论和标签。
- GitHub Issue 与 PR 共用编号空间；编号有歧义时先 `gh pr view`，失败后再 `gh issue view`。

## Wayfinding

- 地图使用一个带 `wayfinder:map` 标签的 Issue。
- 子任务优先使用 GitHub sub-issues；不可用时在正文顶部写 `Part of #<map>`。
- 阻塞关系优先使用 GitHub 原生 issue dependencies；不可用时写 `Blocked by: #<n>`。
- 认领任务后再产生写操作；解决时记录结论、关闭子任务并回填地图。
