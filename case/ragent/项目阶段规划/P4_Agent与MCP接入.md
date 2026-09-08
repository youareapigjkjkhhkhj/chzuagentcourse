# P4 Agent 与 MCP 接入

## 目标

实现 Agent 执行架构（v2 ReAct），接入 MCP 协议实现工具发现与调用。

## 工作分解

### 1. Agent 执行架构

- [ ] ReAct 骨架实现
- [ ] 工具调用抽象
- [ ] 执行上下文管理
- [ ] 流式输出

### 2. MCP 客户端

- [ ] MCP Java SDK 集成
- [ ] stdio 传输实现
- [ ] 连接管理

### 3. 工具发现

- [ ] tools/list 协议
- [ ] 工具注册表
- [ ] 工具 Schema 解析

### 4. 工具调用

- [ ] tools/call 协议
- [ ] 参数提取与校验
- [ ] 结果处理

### 5. MCP Server 配置

- [ ] 配置文件格式
- [ ] Server 生命周期
- [ ] 状态管理

### 6. 示例 MCP Server

- [ ] 天气查询示例
- [ ] 票务查询示例
- [ ] 销售数据示例
- [ ] 联网搜索示例

## 验收条件

- [ ] Agent 能执行 ReAct 循环
- [ ] MCP Server 能被发现和调用
- [ ] 工具参数校验生效
- [ ] 示例 MCP Server 能正常工作
- [ ] 工具调用结果能正确返回

## 技术选型

| 组件 | 选型 | 版本 |
|:---|:---|:---|
| Agent 框架 | AgentScope | 2.0.2 |
| MCP SDK | MCP Java SDK | 1.1.2 |

## 预估周期

1-2 周
