# 09 - Checkpointing：检查点持久化（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `model`、`build_agent`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` / `view_db.py` 是等价的脚本版本，本手册不修改它们。
> - **本模块需要在线模型**：Agent 相关单元格依赖 function calling。离线小模型不支持，概念可先阅读理解。

## 学习目标

**Checkpointing = 将对话状态持久化到数据库**

- `InMemorySaver` → 内存（程序退出即丢失）
- `SqliteSaver` → SQLite 文件（持久化，重启不丢，可跨进程）

1. 用 `SqliteSaver` 把对话写入数据库
2. 模拟"程序重启"后恢复会话
3. 直接查看 / 管理数据库内容

## 0. 准备工作

```bash
pip install -U langchain langchain-groq langgraph langgraph-checkpoint-sqlite python-dotenv
```

把仓库根目录的 `.env.example` 复制为 `.env`，填入 `GROQ_API_KEY=gsk_xxx`。

---

## 单元格 1：初始化模型（在线必需）

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.7,
    max_tokens=300,
)


def build_agent(checkpointer):
    """用指定的 checkpointer 构建 Agent"""
    return create_agent(model=model, tools=[], checkpointer=checkpointer)


print("就绪")
```

---

## 单元格 2：回顾 InMemorySaver 的局限

```python
from langgraph.checkpoint.memory import InMemorySaver

memory_agent = build_agent(InMemorySaver())
# 可用，但：
# - Jupyter 内核重启后历史即消失
# - 无法被另一个进程访问
# - 不适合生产环境
print("InMemorySaver 只存在进程内存中")
```

---

## 单元格 3：SqliteSaver——把对话写进数据库

两个要点：路径直接传文件名（不要加 `sqlite:///` 前缀）；必须用 `with` 语句：

```python
from langgraph.checkpoint.sqlite import SqliteSaver

DB_PATH = "checkpoints.sqlite"

with SqliteSaver.from_conn_string(DB_PATH) as checkpointer:
    agent = build_agent(checkpointer)
    config = {"configurable": {"thread_id": "user_123"}}

    r1 = agent.invoke({
        "messages": [{"role": "user", "content": "我叫张三，我的订单号是 12345"}]
    }, config)
    print("第 1 轮:", r1["messages"][-1].content)
```

`with` 块结束时连接已关闭——效果等同于"程序退出"。

---

## 单元格 4：模拟重启后恢复会话

重新打开同一个数据库文件，历史还在：

```python
with SqliteSaver.from_conn_string(DB_PATH) as checkpointer:
    agent = build_agent(checkpointer)
    config = {"configurable": {"thread_id": "user_123"}}

    r2 = agent.invoke({
        "messages": [{"role": "user", "content": "我的订单号是多少？"}]
    }, config)
    print("重启后:", r2["messages"][-1].content)   # 记得订单号！
```

数据保存在哪里：

```
SqliteSaver:
    对话历史 -> checkpoints.sqlite 文件（持久化）
    ├── thread_id: user_123
    │   ├── checkpoint_1
    │   └── checkpoint_2
    └── thread_id: ...
```

---

## 单元格 5：查看数据库内容

```python
import os
import sqlite3

print(f"数据库大小: {os.path.getsize(DB_PATH) / 1024:.1f} KB")

conn = sqlite3.connect(DB_PATH)
tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"
)]
print("数据表:", tables)
conn.close()
```

也可以运行同目录的 `python view_db.py` 查看更详细的内容。

---

## 单元格 6：多用户持久化管理

所有用户的对话都存在同一个库中，按 thread_id 隔离：

```python
with SqliteSaver.from_conn_string(DB_PATH) as checkpointer:
    agent = build_agent(checkpointer)

    for tid, msg in [
        ("customer_alice", "我想查询物流"),
        ("customer_bob", "我要退货"),
    ]:
        cfg = {"configurable": {"thread_id": tid}}
        r = agent.invoke({"messages": [{"role": "user", "content": msg}]}, cfg)
        print(f"[{tid}] {r['messages'][-1].content[:50]}")
```

删除某个用户的历史（手动操作数据库）：

```python
conn = sqlite3.connect(DB_PATH)
conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", ("customer_bob",))
conn.commit()
conn.close()
print("已清空 customer_bob 的历史")
```

---

## 对比与选型

| 特性 | InMemorySaver | SqliteSaver |
|-----|--------------|-------------|
| 持久化 | 程序退出即丢失 | 持久化到文件 |
| 跨进程 | 不支持 | 支持 |
| 性能 | 快（内存） | 稍慢（磁盘 I/O） |
| 适用 | 开发、测试 | 生产环境 |

路径格式速查：

```python
SqliteSaver.from_conn_string("checkpoints.sqlite")        # 相对路径（当前目录）
SqliteSaver.from_conn_string("C:/data/checkpoints.sqlite") # 绝对路径（Windows 用正斜杠）
SqliteSaver.from_conn_string(":memory:")                    # 内存数据库（测试用）
```

---

## FAQ

### Q1: 忘记用 with 会怎样？

`from_conn_string()` 返回上下文管理器，不用 `with` 可能导致连接未正确释放。始终写 `with ... as checkpointer:`。

### Q2: 数据库会无限增长吗？

会。策略：定期删除旧对话、限制每个 thread 的 checkpoint 数量、定期备份归档。

### Q3: 性能能撑多大？

SQLite 适合中小型应用；大规模高并发建议换 PostgreSQL（LangGraph 同样支持）。

## 核心要点

1. `SqliteSaver.from_conn_string("checkpoints.sqlite")` + `with` 语句
2. 路径直接传文件路径，不要加 `sqlite:///` 前缀
3. 重启后按相同 `thread_id` 访问即可恢复会话
4. 多个进程可共享同一个数据库文件

## 下一步

**10_middleware_basics** —— 自定义中间件：日志、计数、修剪、限流
