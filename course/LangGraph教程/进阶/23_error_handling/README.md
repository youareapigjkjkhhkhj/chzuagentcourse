# 23 - 错误处理（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量，跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。

## 学习目标

| 问题类型 | 武器 |
|---------|------|
| 网络临时错误 | 指数退避重试 |
| 主模型故障 | 模型降级回退 |
| 输出格式错误 | Pydantic 验证 + 重试 |
| 部分功能失败 | 优雅降级 |
| 异常统一管理 | 全局错误处理器 |

## 0. 准备工作

```bash
pip install -U langchain langchain-groq pydantic python-dotenv
```

---

## 单元格 1：初始化模型

```python
import os
import time
import random
import json
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
    max_tokens=300,
)

print("模型就绪")
```

---

## 单元格 2：指数退避重试

```python
def retry_with_backoff(func, max_retries=3, base_delay=1.0):
    """带指数退避的重试装饰器"""
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = min(base_delay * (2 ** attempt), 60)
                    jitter = random.uniform(0, delay * 0.1)
                    print(f"  ⚠️ 尝试 {attempt+1} 失败: {e}")
                    print(f"     等待 {delay+jitter:.1f}s 后重试...")
                    time.sleep(delay + jitter)
                else:
                    print(f"  ❌ 所有 {max_retries} 次尝试均失败")
        raise last_exception
    return wrapper

# 模拟不稳定函数（前2次失败，第3次成功）
call_count = [0]
def unstable_function(query):
    call_count[0] += 1
    if call_count[0] <= 2:
        raise ConnectionError(f"模拟网络错误 (尝试 {call_count[0]})")
    return model.invoke(query)

stable = retry_with_backoff(unstable_function, max_retries=3, base_delay=0.5)
result = stable("1+1等于几？")
print(f"最终成功: {result.content}")
```

---

## 单元格 3：模型降级回退

```python
class FallbackChain:
    """带回退的模型链"""
    def __init__(self, models):
        self.models = models

    def invoke(self, query):
        for i, m in enumerate(self.models):
            try:
                print(f"  尝试模型 {i+1}...")
                return m.invoke(query)
            except Exception as e:
                print(f"  ⚠️ 模型 {i+1} 失败: {e}")
        raise Exception("所有模型都失败")

# 实际使用时可以用不同模型，这里用同一模型演示
fallback = FallbackChain([model, model])
result = fallback.invoke("什么是 Python？一句话回答。")
print(f"结果: {result.content}")
```

---

## 单元格 4：输出验证 + 重试修复

```python
class ProductInfo(BaseModel):
    name: str = Field(description="产品名称")
    price: float = Field(gt=0, description="价格必须大于0")
    category: str = Field(description="类别")

def safe_parse_json(text, default=None):
    """安全解析 JSON，处理 Markdown 代码块"""
    content = text.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        parts = content.split("```")
        if len(parts) >= 2:
            content = parts[1]
    try:
        return json.loads(content.strip())
    except json.JSONDecodeError:
        return default

def extract_product(description, max_retries=3):
    prompt = f"""从描述中提取产品信息，返回 JSON：
{{"name": "产品名称", "price": 数字, "category": "类别"}}
描述: {description}
只返回 JSON。"""

    for attempt in range(max_retries):
        try:
            response = model.invoke(prompt)
            data = safe_parse_json(response.content)
            if data is None:
                raise json.JSONDecodeError("解析失败", response.content, 0)
            product = ProductInfo(**data)
            print(f"  ✅ 验证通过 (第{attempt+1}次)")
            return product
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"  ⚠️ 失败 (第{attempt+1}次): {e}")

    print("  ℹ️ 使用默认值")
    return ProductInfo(name="未知产品", price=0.01, category="未分类")

product = extract_product("蓝牙耳机售价299元，属于电子产品")
print(f"  结果: {product}")
```

---

## 单元格 5：优雅降级

```python
class RobustAssistant:
    def __init__(self, model):
        self.model = model
        self.features = {"summarize": True, "translate": True, "sentiment": True}

    def _safe_call(self, feature, prompt, default="功能暂时不可用"):
        if not self.features.get(feature, False):
            return f"[{feature}] {default}"
        try:
            return self.model.invoke(prompt).content
        except Exception as e:
            print(f"  ⚠️ {feature} 出错: {e}")
            self.features[feature] = False
            return f"[{feature}] {default}"

    def process(self, text):
        return {
            "summary": self._safe_call("summarize", f"一句话总结：{text}"),
            "translation": self._safe_call("translate", f"翻译成英文：{text}"),
            "sentiment": self._safe_call("sentiment", f"分析情感（正面/负面/中性）：{text}"),
        }

assistant = RobustAssistant(model)
# 模拟翻译功能不可用
assistant.features["translate"] = False

results = assistant.process("今天天气真好，适合出去散步。")
for k, v in results.items():
    print(f"  {k}: {v}")
```

---

## 单元格 6：全局错误处理器

```python
class ErrorHandler:
    def __init__(self):
        self.error_log = []

    def handle(self, error, context=None):
        entry = {
            "type": type(error).__name__,
            "message": str(error),
            "context": context,
            "timestamp": time.time()
        }
        self.error_log.append(entry)

        user_messages = {
            "ConnectionError": "网络连接失败，请重试",
            "TimeoutError": "请求超时，请稍后重试",
            "ValueError": "输入数据无效",
        }
        return {
            "success": False,
            "user_message": user_messages.get(entry["type"], "处理请求时出错"),
            "error_type": entry["type"],
            "can_retry": entry["type"] in ["ConnectionError", "TimeoutError"]
        }

    def stats(self):
        by_type = {}
        for e in self.error_log:
            by_type[e["type"]] = by_type.get(e["type"], 0) + 1
        return {"total": len(self.error_log), "by_type": by_type}

handler = ErrorHandler()

# 正常调用
try:
    r = model.invoke("你好！")
    print(f"成功: {r.content}")
except Exception as e:
    print(handler.handle(e, {"action": "test"}))

# 模拟错误
result = handler.handle(ConnectionError("Connection refused"), {"action": "test"})
print(f"错误处理: {result}")
print(f"统计: {handler.stats()}")
```

---

## 单元格 7：超时处理

```python
import concurrent.futures

def invoke_with_timeout(model, query, timeout=30.0):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(model.invoke, query)
        try:
            result = future.result(timeout=timeout)
            return {"success": True, "content": result.content}
        except concurrent.futures.TimeoutError:
            return {"success": False, "error": "请求超时", "timeout": timeout}

result = invoke_with_timeout(model, "你好！", timeout=30.0)
print(result)
```

---

## 核心要点

| 策略 | 适用场景 | 实现方式 |
|------|---------|---------|
| 指数退避重试 | 临时网络错误 | for 循环 + sleep |
| 模型降级 | 主模型故障 | FallbackChain |
| 验证 + 重试 | 输出格式错误 | Pydantic + 循环 |
| 优雅降级 | 部分功能失败 | 功能开关 + 默认值 |
| 全局处理器 | 统一错误管理 | ErrorHandler 类 |
| 超时控制 | 防止无限等待 | ThreadPoolExecutor |

## FAQ

### Q1: 重试次数设多少？

常规 3 次；高可用 5 次；快速失败 1 次。

### Q2: 怎么避免无限重试？

永远用带上限的 for 循环，不要 `while True` 裸重试。

## 下一步

进入 **进阶项目** —— 01_rag_system（RAG 系统）→ 02_multi_agent_support（客服系统）→ 03_research_assistant（研究助手）
