# MCP Connector / Tool 按需加载设计方案

## 1. 目标

解决 MCP 工具数量增长后，全部 Tool Schema 注入模型 Context 导致的：

* Context 占用过大
* Tool Selection 准确率下降
* 首次请求延迟增加
* 多 Connector 场景难以扩展

核心原则：

> **Connector 全量注册，Tool 摘要索引，Schema 按需加载。**

---

## 2. 整体架构

```text
MCP Server
    ↓
Connector Manager
    ↓
Tool Registry
    │
    ├── Tool Metadata / Index
    │
    └── Full Tool Schema（按需获取）
            ↓
       Tool Search
            ↓
       Top-K Tools
            ↓
       Load Schema
            ↓
       Approval / Policy
            ↓
       MCP Tool Call
```

---

## 3. Connector 层

Connector 负责 MCP Server 的生命周期和连接管理。

```json
{
  "id": "blender",
  "name": "Blender",
  "transport": "stdio",
  "status": "connected",
  "toolCount": 28
}
```

Connector 可以拥有任意数量 Tool，但**不直接把全部 Schema 注入模型**。

---

## 4. Tool Registry

连接器启动后发现全部 MCP Tools，并建立本地索引。

```json
{
  "server": "blender",
  "name": "render_scene",
  "description": "Render the current Blender scene",
  "tags": ["render", "image", "scene"],
  "risk": "write"
}
```

Registry 保存：

* tool name
* description
* server
* tags
* risk level
* input schema location
* enabled/disabled 状态

完整 `inputSchema` 按需加载。

---

## 5. Tool Search

向模型提供一个系统级能力：

```text
search_tools(query)
```

例如：

```text
search_tools("Blender render scene to 4K PNG")
```

Registry 返回 Top-K：

```text
blender.render_scene
blender.set_render_resolution
blender.export_image
```

然后 Harness 只把这几个 Tool 的完整 Schema 注入当前 Context。

---

## 6. Tool Loading 策略

默认：

```text
Core Tools
    → 始终加载

MCP Tools
    → 按需搜索
    → Top-K
    → 动态加载 Schema
```

允许 Connector / Tool 配置：

```text
alwaysLoad: true
```

用于高频、核心 Tool。

---

## 7. Approval / Risk

Approval 独立于 Tool Search。

建议：

```text
READ
    → 默认自动执行

WRITE
    → 首次调用确认

DESTRUCTIVE
    → 每次确认
```

并支持：

```text
Remember for this connector
Remember for this tool
Always ask
Never ask
```

这样“工具发现”和“安全策略”两个系统不会耦合。

---

## 8. Tool Naming

统一使用 namespace，避免不同 MCP Server 出现同名 Tool：

```text
mcp_blender__render_scene
mcp_github__create_issue
mcp_notion__search
mcp_slack__send_message
```

---

## 9. UI

Connector 页面不再强调：

> 28 个工具全部随会话下发给模型

改为：

```text
Blender
3D modeling · rendering · automation

● Connected
28 tools · On-demand
```

用户可以查看 Tool 列表，但模型默认通过 Tool Search 按需加载。

---

## 10. 核心收益

```text
Connector 数量：    不限制
Tool 数量：          不限制
模型初始 Context：  保持较小
Tool Schema：        按需加载
权限控制：           独立
搜索 / Ranking：     Harness 统一处理
```

最终原则：

> **MCP Runtime 管连接，Tool Registry 管发现，Tool Search 管选择，Policy 管权限，Model 负责决策。**
