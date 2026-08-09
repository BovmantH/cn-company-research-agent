# Domain Docs

本仓库采用单一领域上下文布局。

## 探索代码前

- 若根目录存在 `CONTEXT.md`，先读取与当前任务相关的领域词汇和边界。
- 读取 `docs/adr/` 中触及当前模块的架构决策。
- 文件不存在时直接继续，不为填目录而创建空文档；需要形成稳定术语或决策时再补。

## 布局

```text
/
├── CONTEXT.md
├── docs/adr/
└── backend/
```

## 使用规则

- Issue、规格、测试和代码命名优先使用 `CONTEXT.md` 已定义的术语，避免同义词漂移。
- 新概念若无法映射到现有词汇，先判断是命名偏差还是领域缺口。
- 实现若与既有 ADR 冲突，必须明确指出冲突并说明是否需要重开决策，不能静默覆盖。
- Company Intelligence、Research Job、Evidence、Report Assembly 和 Web Research 是不同模块边界，不因当前文件布局相近而合并语义。
