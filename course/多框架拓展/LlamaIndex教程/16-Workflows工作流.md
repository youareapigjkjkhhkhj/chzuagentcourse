# 16 - Workflows 工作流

本篇目标：掌握 LlamaIndex 的核心编排抽象——**事件驱动的 Workflow**：步骤、事件、`Context`、并发、流式与人工协同。

## 16.1 前置准备

```bash
pip install llama-index
# Workflows 也可独立安装：pip install llama-index-workflows
```

> 导入路径说明：为保持 `llama_index` API 稳定，安装 `llama-index-core` 或伞包时，Workflows 通过 **`llama_index.core.workflow`** 访问；独立安装时用 `workflows`。

## 16.2 什么是 Workflow（官方定义）

> A workflow is an event-driven, step-based way to control the execution flow of an application.

模型很简单：

- 应用被拆成若干 **step**
- 一个 step 接收一个事件 → 干活 → 返回另一个事件
- 返回的事件触发**下一个类型注解能接受它的 step**

```text
StartEvent ──▶ @step A ──▶ MyEvent ──▶ @step B ──▶ StopEvent
```

为什么不是 DAG：循环与分支写在图边里会难以阅读；事件 + 普通 Python 更自然。

| 需求 | 写法 |
|------|------|
| 分支 | 普通 `if`，返回不同事件类型 |
| 循环 | step 返回一个由更早的 step 处理的事件 |
| 并发 | step 返回 `list[Event]`，另一个 step 接收 `list[Event]` |
| 动态 | 用 `Context` 直接 `send_event` |

## 16.3 第一个 Workflow（官方 JokeFlow 示例）

```python
from workflows import Workflow, step
from workflows.events import Event, StartEvent, StopEvent

# pip install llama-index-llms-openai
from llama_index.llms.openai import OpenAI


class JokeEvent(Event):
    joke: str


class JokeFlow(Workflow):
    llm = OpenAI(model="gpt-4.1")

    @step
    async def generate_joke(self, ev: StartEvent) -> JokeEvent:
        topic = ev.topic
        prompt = f"Write your best joke about {topic}."
        response = await self.llm.acomplete(prompt)
        return JokeEvent(joke=str(response))

    @step
    async def critique_joke(self, ev: JokeEvent) -> StopEvent:
        joke = ev.joke
        prompt = f"Give a thorough analysis and critique of the following joke: {joke}"
        response = await self.llm.acomplete(prompt)
        return StopEvent(result=str(response))


w = JokeFlow(timeout=60, verbose=False)
result = await w.run(topic="pirates")
print(str(result))
```

脚本入口（官方推荐写法）：

```python
async def main():
    w = JokeFlow(...)
    result = await w.run(...)
    print(result)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## 16.4 事件

- 事件是**用户定义的 Pydantic 对象**
- `StartEvent`：入口，可携带任意属性（`ev.topic`；不确定时用 `ev.get("topic")`）。**可子类化**以获得类型安全
- `StopEvent`：出口，返回 `result`（可以是任意对象）。**可子类化**

```python
from workflows.events import StartEvent, StopEvent


class QueryStart(StartEvent):
    question: str


class AnswerStop(StopEvent):
    answer: str
    sources: list[str]
```

## 16.5 流式事件

`.run()` 返回 `WorkflowHandler`，它可 await，也可流式消费事件：

```python
handler = w.run(topic="pirates")

async for ev in handler.stream_events():
    print(ev)

result = await handler
```

## 16.6 并发：list[Event]

```python
class WorkItem(Event):
    item: str


class Gathered(Event):
    results: list[str]


class ParallelFlow(Workflow):

    @step
    async def dispatch(self, ev: StartEvent) -> list[WorkItem]:
        items = ev.get("items", [])
        return [WorkItem(item=i) for i in items]

    @step(num_workers=4)
    async def handle_item(self, ev: WorkItem) -> str:
        return f"done: {ev.item}"

    @step
    async def gather(self, ev: list[str]) -> StopEvent:
        return StopEvent(result=ev)
```

> `num_workers` 控制该 step 的并发度；返回 `list[Event]` 的 step 与接收 `list[Event]` 的 step 配对实现批量分发与汇聚。

## 16.7 Context：共享状态与动态事件

| API | 用途 |
|-----|------|
| `ctx.store` | 每个 run 的共享状态（字典式） |
| `ctx.send_event(event)` | 增量/动态地发出事件（数量未知、或运行中从外部发） |
| `ctx.collect_events(events, expected)` | 手动等待一组事件 |
| `Resource(...)` | 注入客户端、索引、模型、配置等**不应进入序列化状态**的依赖 |

```python
from workflows import Workflow, step
from workflows.events import StartEvent, StopEvent, Event
from workflows.context import Context


class StepDone(Event):
    value: str


class StateFlow(Workflow):

    @step
    async def start(self, ctx: Context, ev: StartEvent) -> StepDone:
        await ctx.store.set("counter", 0)
        return StepDone(value=ev.get("input", ""))

    @step
    async def finish(self, ctx: Context, ev: StepDone) -> StopEvent:
        counter = await ctx.store.get("counter")
        await ctx.store.set("counter", counter + 1)
        return StopEvent(result={"value": ev.value, "counter": counter})
```

## 16.8 校验（Validation）

运行前 Workflows 会根据 step 签名校验事件图：起点/终点是否存在、产出的事件是否有消费者、消费的事件是否有生产者、是否有死路。

| 症状 | 常见原因 |
|------|----------|
| 消费了从未产出的事件 | 缺少返回注解，或该事件只用 `ctx.send_event` 动态发送 |
| 产出了无人消费的事件 | 下一步的事件类型写错，或分支没写完 |
| 没有终止事件 | 没有可达的 step 返回 `StopEvent` |

动态 step 可跳过可达性检查：

```python
@step(skip_graph_checks=["reachability"])
async def receive_webhook(self, ev: WebhookEvent) -> StopEvent:
    ...
```

也可在测试/启动时调用 `workflow.validate()`。

## 16.9 人工协同（HITL）

Workflow 运行中可暂停等待人类输入——通过事件与 `send_event` 实现：

```python
from workflows.events import InputRequiredEvent, HumanResponseEvent


class StoryFlow(Workflow):

    @step
    async def draft(self, ev: StartEvent) -> InputRequiredEvent | StopEvent:
        draft = await self.llm.acomplete(f"Write a story about {ev.topic}")
        return InputRequiredEvent(prefix="草稿如下，请反馈：", result=str(draft))

    @step
    async def handle_feedback(self, ev: HumanResponseEvent) -> StopEvent:
        final = await self.llm.acomplete(f"根据反馈修改：{ev.response}")
        return StopEvent(result=str(final))


handler = flow.run(topic="太空探险")

async for ev in handler.stream_events():
    if isinstance(ev, InputRequiredEvent):
        handler.ctx.send_event(HumanResponseEvent(response=input(ev.prefix)))

result = await handler
```

> 官方示例 "Human In The Loop: Story Crafting" 演示了交互式、有状态的 workflow 运行。

## 16.10 RAG + 重排的 Workflow

把检索与重排写成两个 step：

```python
class Retrieved(Event):
    nodes: list[str]


class RAGFlow(Workflow):
    @step
    async def retrieve(self, ev: StartEvent) -> Retrieved:
        nodes = await retriever.aretrieve(ev.get("question"))
        return Retrieved(nodes=[n.text for n in nodes])

    @step
    async def rerank(self, ev: Retrieved) -> StopEvent:
        # 这里可插入 reranker / 阈值过滤
        context = "\n\n".join(ev.nodes[:3])
        answer = await llm.acomplete(f"依据资料回答：\n{context}\n问题：{ev.get('question')}")
        return StopEvent(result=str(answer))
```

## 16.11 持久化与恢复

官方示例 "Writing Durable Workflows" 演示了**对 workflow context 做 checkpoint 并在重启后恢复运行**——长流程任务的必备能力。

## 关键 API 速查

| API | 说明 |
|-----|------|
| `Workflow` 子类 + `@step` | 定义工作流 |
| `StartEvent` / `StopEvent`（可子类化） | 入口/出口事件 |
| `await w.run(**kwargs)` → `WorkflowHandler` | 运行（kwargs 成为 StartEvent 字段） |
| `handler.stream_events()` | 流式消费事件 |
| `return list[Event]` / 接收 `list[Event]` | 并发分发与汇聚 |
| `@step(num_workers=N)` | 并发度 |
| `ctx.store` / `ctx.send_event` / `ctx.collect_events` | 共享状态与动态事件 |
| `Resource(...)` | 注入非序列化依赖 |
| `workflow.validate()` | 图校验 |
| `@step(skip_graph_checks=["reachability"])` | 跳过可达性检查 |

## 注意事项

- Workflows 是**异步优先**的：脚本请统一 `asyncio.run(main())`。
- 事件类型注解决定连线——写错注解会表现为"流程不动"或校验报错。
- 共享状态放 `ctx.store`，外部依赖（DB 连接、索引、模型）放 `Resource`。
- 长流程务必设置 `timeout` 并做 checkpoint。

## 下一步

→ [17-评估与部署.md](17-评估与部署.md)：评估效果、托管服务与部署形态。
