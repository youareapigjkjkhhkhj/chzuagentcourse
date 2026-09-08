# 12 - 多智能体协作 Agent Team

本篇目标：让多个智能体协同工作——顺序流水线、leader-worker 团队、任务规划。AgentScope 2.0 **原生支持多智能体**，核心是消息驱动 + Pipeline 编排。

## 12.1 前置准备

```bash
pip install agentscope[full]
export DASHSCOPE_API_KEY="sk-你的密钥"
```

## 12.2 消息驱动的通信

2.0 以消息驱动实现智能体间通信。底层 `msghub` 模块统一管理消息路由，消息支持多模态（文字/图片/语音）。

## 12.3 顺序流水线 SequentialPipeline

把多个智能体串成流水线，前一个的输出作为后一个的输入：

```python
import os
import asyncio

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.pipeline import SequentialPipeline
from agentscope.tool import Toolkit, Bash, Read, Write, Edit


def make_agent(name: str, sys_prompt: str) -> Agent:
    return Agent(
        name=name,
        system_prompt=sys_prompt,
        model=DashScopeChatModel(
            credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
            model="qwen-plus",
        ),
        toolkit=Toolkit(tools=[Bash(), Read(), Write(), Edit()]),
    )


async def main() -> None:
    writer = make_agent("Writer", "你是专业作家，擅长创作故事。")
    critic = make_agent("Critic", "你是资深评论家，精准分析故事优缺点。")

    # 顺序执行：作家先写，评论家再评
    pipeline = SequentialPipeline([writer, critic])
    result = await pipeline.run(
        UserMsg(name="user", content="写一个科幻短篇故事，然后给出评价")
    )
    print(result.content)


asyncio.run(main())
```

## 12.4 协作模式

2.0 原生支持多种协作模式：

- **路由式任务分发**：按规则分发到不同智能体
- **并行化处理**：多个智能体同时处理不同子任务
- **协调者-工作者（leader-worker）**：主智能体调度工作智能体
- **评估者-优化者闭环**：智能体间迭代优化

## 12.5 Agent Team（leader-worker + 任务规划）

2.0 内置 **Agent Team** 能力：Leader 智能体把任务拆解成可追踪的计划，派发给 Worker 并行执行，执行中持续修订计划。SDK 提供内置 team tools 与 task planning 工具。

**服务层（推荐体验）**：在 Agent Service 的 Web UI 里直接「创建团队 + 下达任务」，内置团队工具开箱即用（见 [16-AgentService与部署.md](16-代理Service与部署.md)）。

示例（自然语言下达团队任务）：

```text
Create a team to survey what API are supported by these LLM vendors
```

→ Leader 创建团队 → 拆出「逐厂商调研 API 能力」子任务 → 派发多个 Worker 并行 → 汇总为结构化对比报告。

## 12.6 完整多智能体脚本（含工具）

```python
import os
import asyncio
from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit, Bash, Grep, Glob, Read, Write, Edit
from agentscope.pipeline import SequentialPipeline

# 三个角色串联：调研 → 写作 → 审校
researcher = Agent(name="Researcher", system_prompt="你做技术调研。",
                   model=DashScopeChatModel(credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]), model="qwen-plus"),
                   toolkit=Toolkit(tools=[Bash(), Grep(), Glob(), Read(), Write(), Edit()]))
writer = Agent(name="Writer", system_prompt="你把调研写成报告。",
               model=DashScopeChatModel(credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]), model="qwen-plus"))
editor = Agent(name="Editor", system_prompt="你审校报告。",
               model=DashScopeChatModel(credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]), model="qwen-plus"))

pipeline = SequentialPipeline([researcher, writer, editor])
result = await pipeline.run(UserMsg(name="user", content="调研 AgentScope 2.0 的核心能力，产出一份报告"))
print(result.content)
```

## 关键 API 速查

| API | 说明 |
|-----|------|
| `SequentialPipeline([a1, a2, ...])` | 顺序流水线 |
| `await pipeline.run(msg)` | 运行流水线（async） |
| `msghub` | 底层消息路由（消息驱动通信） |
| Agent Team / team tools | Leader-worker 协作（服务层或 SDK 内置） |

## 2.0 注意事项

- 2.0 多智能体用 `pipeline.SequentialPipeline`，**不要**用 1.0 旧 `SequentialPipeline` 签名或 `MsgHub` 类（已重构）。
- `pipeline.run(...)` 是 `async`，需 `await`。
- 复杂团队协作优先用 **Agent Service** 的 Web UI（可视化、可中断、可规划），见 16 篇。

## 下一步

→ [13-检索增强RAG.md](13-检索增强RAG.md)：给智能体接上知识库。
