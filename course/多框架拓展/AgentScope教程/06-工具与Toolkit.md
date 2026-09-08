# 06 - 工具与 Toolkit

本篇目标：让智能体「动手干活」。学会用 `@tool` 自定义工具、使用内置「程序员工具全家桶」，并用 `Toolkit` 组装进 `Agent`。

## 6.1 前置准备

```bash
pip install agentscope[full]   # 内置工具来自工作区/沙箱后端，建议装 full
export DASHSCOPE_API_KEY="sk-你的密钥"
```

## 6.2 自定义工具：@tool 装饰器

给普通 Python 函数加 `@tool`，函数**自动变成可被智能体调用的工具**；**文档字符串即工具说明书**（模型据此决定何时调用）。

```python
from agentscope.tool import tool


@tool  # 装饰器一加，函数即成为可调用工具
def current_time(timezone: str = "Asia/Shanghai") -> str:
    """返回指定时区的当前时间，参数 timezone 为 IANA 时区名"""
    from datetime import datetime, timezone as tz
    return datetime.now(tz(tz(timezone))).isoformat()


# 直接调用验证（不依赖模型）
print(current_time("Asia/Shanghai"))
```

把工具挂进智能体：

```python
import os
from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit

agent = Agent(
    name="Friday",
    system_prompt="You are a helpful assistant. Use tools when needed.",
    model=DashScopeChatModel(
        credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
        model="qwen-plus",
    ),
    toolkit=Toolkit(tools=[current_time]),
)

# 智能体会自动识别「时间」意图并调用 current_time
reply = await agent.reply(UserMsg(name="user", content="现在上海几点了？"))
```

> `@tool` 函数需有**清晰的类型注解与 docstring**，模型靠它们理解参数与用途。

## 6.3 内置工具全家桶

AgentScope 内置一套「程序员工具」，天然绑定工作区沙箱：

| 工具类 | 作用 |
|--------|------|
| `Bash()` | 执行 shell 命令 |
| `Read()` | 读文件 |
| `Write()` | 写文件 |
| `Edit()` | 改文件 |
| `Grep()` | 内容搜索 |
| `Glob()` | 文件名匹配 |

```python
from agentscope.tool import Toolkit, Bash, Grep, Glob, Read, Write, Edit

toolkit = Toolkit(tools=[Bash(), Grep(), Glob(), Read(), Write(), Edit()])

agent = Agent(
    name="Friday",
    system_prompt="You are a coding assistant.",
    model=DashScopeChatModel(
        credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
        model="qwen-plus",
    ),
    toolkit=toolkit,
)
# 你说「列出当前目录的 Python 文件」→ 自动调 Glob
# 你说「把对话总结成 note.md」→ 自动调 Write 落盘
```

## 6.4 从工作区加载工具

更推荐的方式：让工具全部来自 `LocalWorkspace`（沙箱隔离，见 [11-工作区与沙箱Workspace.md](11-工作区与沙箱Workspace.md)）。

```python
import os
from agentscope.tool import Toolkit
from agentscope.workspace import LocalWorkspace

async with LocalWorkspace(workdir="./workspace") as ws:
    toolkit = Toolkit(tools=await ws.list_tools())  # 工具与技能都来自工作空间
```

## 6.5 注册函数式工具

也可把普通可调用对象注册进 `Toolkit`（适合 `execute_python_code` / `execute_shell_command` 等内置函数式工具）：

```python
from agentscope.tool import Toolkit, execute_python_code, execute_shell_command

toolkit = Toolkit()
toolkit.register_tool_function(execute_python_code)
toolkit.register_tool_function(execute_shell_command)
```

> `execute_python_code` / `execute_shell_command` 的具体导入路径以官方文档为准；日常开发优先用 6.3 的 `Bash()` / `Read()` 等类式工具。

## 6.6 工具响应截断（防上下文溢出）

长响应可用「截断保险丝」处理，避免撑爆上下文：

```python
def chunking_too_long_tool_response(tool_use, tool_response):
    budget = 8194 * 5  # 约 40KB 上限
    for block in tool_response.content:
        if block["type"] == "text" and len(block["text"]) > budget:
            block["text"] = block["text"][:budget]  # 超出即截断
            budget = 0
        elif block["type"] == "text":
            budget -= len(block["text"])
    return tool_response
```

## 关键 API 速查

| API | 说明 |
|-----|------|
| `@tool` | 装饰函数 → 工具 |
| `Toolkit(tools=[...])` | 组装工具集合 |
| `Bash() / Read() / Write() / Edit() / Grep() / Glob()` | 内置工具类 |
| `toolkit.register_tool_function(fn)` | 注册函数式工具 |

## 2.0 注意事项

- 自定义工具**必须有 docstring + 类型注解**，否则模型不会调用。
- 内置文件/命令工具来自**工作区**，天然隔离；直接 `Bash()` 在本地执行，生产环境务必配合权限系统（见 [09-权限与人工协同.md](09-权限与人工协同.md)）。
- 2.0 的 `Toolkit` 取代 1.0 手动 `tools=[...]` 裸列表 + 全局注册的方式，组装更清晰。

## 下一步

→ [07-ReAct循环与工具调用.md](07-ReAct循环与工具调用.md)：`Agent` 内置 ReAct 循环如何自动推理-调用工具，以及中断/恢复。
