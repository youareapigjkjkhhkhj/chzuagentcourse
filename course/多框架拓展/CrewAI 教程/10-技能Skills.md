# 10 - 技能 Skills

本篇目标：理解 CrewAI 的 **Skills（技能）** 系统——通过 SKILL.md 文件给 Agent 注入领域专业知识。

## 10.1 什么是 Skill？

**Skill 是一个自包含的目录**，为 Agent 提供领域特定的指令、指南和参考资料。每个 Skill 由 **SKILL.md** 定义，包含 YAML frontmatter 和 Markdown 正文。

**工作原理**：
1. Agent 首先接收每个已配置 Skill 的**名称和描述**
2. 当描述适用于当前请求时，Agent 加载该 Skill 的**完整指令**
3. 这样保持无关指令不出现在上下文中，同时按需提供专业知识

> 一句话：Skill 是"领域专家手册"，Agent 按需查阅，不需要改代码。

## 10.2 快速开始

### 步骤 1：用 CLI 创建 Skill

```bash
# 在 crew 项目内创建
crewai create skill code-review

# 不在项目中时强制在当前目录创建
crewai create skill code-review --no-project
```

创建后在 crew 项目内生成：

```
your_crew/
├── skills/
│   └── code-review/
│       └── SKILL.md
```

### 步骤 2：编写 SKILL.md

```markdown
---
name: code-review
description: 指导 Agent 进行生产级代码审查的专业技能。
---

# 代码审查

## 审查清单

1. **正确性**：逻辑是否正确？边界条件是否处理？
2. **安全性**：是否存在安全漏洞（SQL注入、XSS等）？
3. **性能**：是否存在明显性能问题？
4. **可维护性**：代码是否清晰、可读、可扩展？
5. **最佳实践**：是否遵循项目规范和语言惯例？

## 审查流程

对于每个 PR：
1. 阅读 diff，理解变更意图
2. 运行测试，确认不会引入回归
3. 逐项对照上述清单
4. 提供具体、可执行的反馈
```

### 步骤 3：挂载到 Agent

```python
from crewai import Agent

code_reviewer = Agent(
    role="代码审查专家",
    goal="审查代码质量",
    backstory="资深工程师，负责保证代码质量",
    skills=["code-review"],  # 挂载 skill
    tools=[],  # 可以有工具也可以没有
)
```

Agent 现在同时具备：**专业知识**（从 Skill 加载）和**能力**（从 Tools）。

## 10.3 Skills + Tools 协作模式

### 模式 1：仅 Skill（领域专长，无需操作）

```python
# 需要领域知识但不需要调用外部服务
analyst = Agent(
    role="金融分析师",
    goal="分析财务报告",
    backstory="资深财务分析师",
    skills=["financial-analysis"],
    # 不需要 tools
)
```

### 模式 2：仅 Tools（操作能力，无需特殊专长）

```python
# 需要采取行动但不需要领域专属指令
filer = Agent(
    role="文件处理员",
    goal="整理文件",
    backstory="IT 运维人员",
    skills=[],
    tools=[FileReadTool(), FileWriteTool()],
)
```

### 模式 3：Skills + Tools（专长 + 操作）——最常见模式

```python
# Skill 提供"如何做"，Tools 提供"能做什么"
data_agent = Agent(
    role="数据分析师",
    goal="分析用户数据",
    backstory="数据科学专家",
    skills=["data-analysis"],
    tools=[
        FileReadTool(),
        SQLDatabaseTool(),
        MatplotlibTool(),
    ],
)
```

### 模式 4：Skills + MCPs

Skill 与 MCP 服务器配合，方式和 Tools 相同：

```python
agent = Agent(
    role="数据库管理员",
    goal="管理数据库",
    backstory="DBA 专家",
    skills=["database-admin"],
    tools=[mcp_db_tool],  # MCP 工具也可以
)
```

### 模式 5：Skills + Apps

Skill 可以指导 Agent 如何使用平台集成：

```python
agent = Agent(
    role="客服专员",
    goal="处理用户工单",
    backstory="资深客服专家",
    skills=["zendesk-support"],
    tools=[zendesk_app_tool],
)
```

## 10.4 Skill 生命周期管理

Skills 有完整生命周期，由 CLI 管理：

```bash
# 创建
crewai create skill my-skill

# 发布（可选，用于分享）
crewai skill publish

# 安装（从市场安装）
crewai skill install public_skill_name
```

## 10.5 Skill 与 Tools 的选择决策

| 需要什么 | 用什么 |
|----------|--------|
| 领域专属指令、工作规范、最佳实践 | **Skill** |
| 外部操作能力（搜索、文件、API） | **Tool** |
| 需要专业指令 + 操作能力 | **Skill + Tool** |
| 连接外部 MCP 服务器 | **Skill + MCP** |
| 使用平台集成 | **Skill + App** |

## 10.6 SKILL.md 格式规范

```markdown
---
name: skill-name              # 必填：Skill 名称
description: 一句话描述      # 必填：何时使用此 Skill
---

# 正文标题

（正文内容 — 当 Agent 加载此 Skill 时的完整指令）
```

**要点**：
- `description` 是 Agent 判断"该不该加载此 Skill"的依据，必须写清何时适用
- 正文使用 Markdown，可以包含列表、步骤、代码示例、模板等
- Skill 可以包含多个文件（如参考文档、模板），但 `SKILL.md` 是入口

## 下一步

→ [11-规划Planning.md](11-规划Planning.md)：让 Crew 在任务前进行逐步规划。
