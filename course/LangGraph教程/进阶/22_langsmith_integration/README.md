# 22 - LangSmith 集成（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量，跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。
> - **LangSmith 是可选的**：即使没有 LANGSMITH_API_KEY，所有代码也能正常运行（追踪数据不发送）。

## 学习目标

1. LangSmith 追踪配置
2. 自动追踪与手动 `@traceable` 标记
3. 自定义元数据和标签
4. 性能监控与错误追踪
5. 多步骤工作流追踪

## 0. 准备工作

```bash
pip install -U langchain langchain-groq langsmith python-dotenv
```

可选：在 `.env` 中配置 `LANGSMITH_API_KEY` 以启用完整追踪。

---

## 单元格 1：初始化模型 + LangSmith

```python
import os
import time
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

# LangSmith 配置（可选）
LANGSMITH_ENABLED = bool(os.environ.get("LANGSMITH_API_KEY"))
if LANGSMITH_ENABLED:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = os.environ.get("LANGSMITH_PROJECT", "langchain-study")
    print("✅ LangSmith 追踪已启用")
else:
    print("ℹ️ 未配置 LANGSMITH_API_KEY，追踪数据仅本地记录")

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
    max_tokens=300,
)

print("模型就绪")
```

---

## 单元格 2：基本追踪

启用追踪后，所有 LLM 调用自动记录到 LangSmith（如有配置）：

```python
response = model.invoke("什么是 LangSmith？一句话回答。")
print(response.content)

if LANGSMITH_ENABLED:
    print("→ 追踪数据已发送到 LangSmith")
```

---

## 单元格 3：带元数据的追踪

```python
from langchain_core.runnables import RunnableConfig

config = RunnableConfig(
    metadata={
        "user_id": "user_12345",
        "session_id": "session_67890",
        "request_type": "question",
        "app_version": "1.0.0"
    },
    tags=["study", "module_22", "demo"]
)

response = model.invoke(
    "LangSmith 有什么用？",
    config=config
)
print(response.content)
print(f"元数据: user_id={config.metadata['user_id']}, tags={config.tags}")
```

---

## 单元格 4：性能监控

```python
questions = [
    "1+1等于几？",
    "解释什么是机器学习，100字以内。",
    "写一个计算斐波那契数列的 Python 函数。"
]

results = []
for i, q in enumerate(questions, 1):
    config = RunnableConfig(
        metadata={"test_id": f"perf_{i}", "complexity": ["low", "medium", "high"][i-1]},
        tags=["performance_test"]
    )
    start = time.time()
    response = model.invoke(q, config=config)
    elapsed = time.time() - start

    results.append({"question": q[:30], "length": len(response.content), "time": elapsed})
    print(f"测试{i}: {elapsed:.2f}s | {len(response.content)} 字符")

print(f"\n平均耗时: {sum(r['time'] for r in results)/len(results):.2f}s")
```

---

## 单元格 5：错误追踪

```python
from langchain_core.runnables import RunnableConfig

def risky_operation(query: str, should_fail: bool = False):
    config = RunnableConfig(
        metadata={"operation_type": "risky", "should_fail": should_fail},
        tags=["error_test"]
    )
    if should_fail:
        raise ValueError("模拟的错误：请求参数无效")
    return model.invoke(query, config=config)

# 成功
try:
    r = risky_operation("你好！")
    print(f"成功: {r.content}")
except Exception as e:
    print(f"失败: {e}")

# 失败
try:
    r = risky_operation("你好！", should_fail=True)
except Exception as e:
    print(f"捕获错误: {e}")
    print("错误信息已记录（如启用 LangSmith）")
```

---

## 单元格 6：自定义追踪装饰器

没有 LangSmith 也能用的本地追踪：

```python
from functools import wraps

def custom_traceable(name=None, tags=None):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            func_name = name or func.__name__
            start = time.time()
            print(f"  🔍 开始: {func_name}")
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                print(f"  ✅ 完成: {func_name} ({elapsed:.2f}s)")
                return result
            except Exception as e:
                elapsed = time.time() - start
                print(f"  ❌ 失败: {func_name} ({elapsed:.2f}s) - {e}")
                raise
        return wrapper
    return decorator

@custom_traceable(name="summarize", tags=["demo"])
def summarize(text: str) -> str:
    return model.invoke(f"一句话总结：{text}").content

result = summarize("Python 是一门简洁强大的编程语言，广泛应用于 AI、Web 和数据科学。")
print(f"摘要: {result}")
```

---

## 单元格 7：多步骤工作流追踪

```python
parent_config = RunnableConfig(
    metadata={"workflow": "content_creation"},
    tags=["multi_step", "workflow"]
)

print("内容创作工作流:")

# 步骤1：生成大纲
c1 = RunnableConfig(metadata={**parent_config.metadata, "step": "outline"}, tags=["step_1"])
outline = model.invoke("为'AI的未来'生成3点大纲。", config=c1)
print(f"  大纲: {outline.content[:80]}...")

# 步骤2：扩展
c2 = RunnableConfig(metadata={**parent_config.metadata, "step": "expand"}, tags=["step_2"])
expanded = model.invoke(f"扩展第一点（50字以内）：{outline.content}", config=c2)
print(f"  扩展: {expanded.content[:80]}...")

# 步骤3：润色
c3 = RunnableConfig(metadata={**parent_config.metadata, "step": "polish"}, tags=["step_3"])
polished = model.invoke(f"润色以下文字：{expanded.content}", config=c3)
print(f"  最终: {polished.content}")

print("✅ 所有步骤已追踪记录")
```

---

## 核心要点

1. **自动追踪**：启用 LangSmith 后，所有 LLM 调用自动记录
2. **RunnableConfig** 添加元数据和标签，方便过滤和分析
3. **@traceable** 自定义追踪装饰器，适用于非 LLM 函数
4. LangSmith 是**可选依赖**，不影响代码运行
5. 没有 LangSmith Key 时，追踪数据仅本地记录

## FAQ

### Q1: LangSmith 免费吗？

免费层：每月 5000 条 traces，足够学习和小规模生产使用。

### Q2: 怎么查看追踪数据？

访问 [smith.langchain.com](https://smith.langchain.com)，在项目页面查看完整执行链路。

### Q3: 生产环境要注意什么？

设置合适的采样率；敏感数据脱敏；为不同环境用不同 project。

## 下一步

**23_error_handling** —— 错误处理：重试、降级、验证、超时
