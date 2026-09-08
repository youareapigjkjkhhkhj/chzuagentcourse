# 12 - Validation & Retry：验证和重试（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `model`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` / `test.py` 是等价的脚本版本，本手册不修改它们。
> - **在线 / 离线说明**：【单元格 2、3】的 Pydantic 验证是纯本地代码，任何环境都能跑；【单元格 4】起涉及 LLM 调用，需在线模型。

## 学习目标

生产环境要处理三类问题，各有对应武器：

| 问题 | 武器 |
|-----|------|
| 网络错误（临时性） | `with_retry()` |
| 模型故障 | `with_fallbacks()` |
| 输出质量差 | Pydantic 验证 + 重试循环 |

## 0. 准备工作

```bash
pip install -U langchain langchain-groq pydantic python-dotenv
```

把仓库根目录的 `.env.example` 复制为 `.env`，填入 `GROQ_API_KEY=gsk_xxx`。

---

## 单元格 1：初始化模型（在线必需）

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
    max_tokens=300,
)

print("就绪")
```

---

## 单元格 2：Pydantic 约束验证（纯本地）

Field 约束 + 自定义验证器，不调用 LLM 也能测试：

```python
from pydantic import BaseModel, Field, field_validator, ValidationError

class User(BaseModel):
    name: str = Field(min_length=2, max_length=20)
    age: int = Field(ge=0, le=150)          # 0-150 岁
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if "@" not in v:
            raise ValueError("邮箱必须包含 @")
        return v


# 通过验证
user = User(name="张三", age=30, email="zhangsan@test.com")
print("合法:", user)

# 触发验证失败
try:
    User(name="张", age=200, email="invalid")
except ValidationError as e:
    for err in e.errors():
        print(f"字段 {err['loc']}: {err['msg']}")
```

Field 约束速查：

| 约束 | 用途 | 示例 |
|-----|------|------|
| `gt` / `ge` | 数值 > / >= | `Field(gt=0)` |
| `lt` / `le` | 数值 < / <= | `Field(le=100)` |
| `min_length` / `max_length` | 字符串长度 | `Field(min_length=2)` |
| `pattern` | 正则表达式 | `Field(pattern=r'^\d{11}$')` |

---

## 单元格 3：跨字段验证（纯本地）

用 `info.data` 访问其他字段做联合校验：

```python
class Article(BaseModel):
    title: str
    content: str
    word_count: int = Field(description="声称的字数")

    @field_validator("word_count")
    @classmethod
    def validate_word_count(cls, v, info):
        actual = len(info.data.get("content", ""))
        if abs(v - actual) > max(actual * 0.1, 5):   # 允许 10% 误差
            raise ValueError(f"字数不匹配: 声称 {v}, 实际 {actual}")
        return v


Article(title="测试", content="五个字", word_count=100)
```

上面这行会抛 ValidationError——这正是我们想要的防线。

---

## 单元格 4：with_retry()——网络错误自动重试（在线）

```python
llm_with_retry = model.with_retry(
    retry_if_exception_type=(ConnectionError, TimeoutError),
    wait_exponential_jitter=True,   # 指数退避 + 随机抖动
    stop_after_attempt=3,
)

resp = llm_with_retry.invoke("你好")
print(resp.content)
```

工作原理：失败后等待 1s → 重试 → 再失败等 2s → 重试，最多 3 次。

适用：网络波动、临时限流、超时。
不适用：提示词写错、参数非法（重试永远不会成功）。

---

## 单元格 5：with_fallbacks()——模型降级（在线）

主模型挂了自动切备用模型：

```python
primary = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
)
fallback = init_chat_model(
    "groq:llama-3.1-8b-instant",
    api_key=os.getenv("GROQ_API_KEY"),
)

robust_llm = primary.with_fallbacks([fallback])

print(robust_llm.invoke("一句话介绍 Python").content)
# 主模型正常 -> 用主模型；失败 -> 自动切换备用
```

---

## 单元格 6：结构化输出 + 验证重试循环（在线）

LLM 输出不符合约束时，把错误信息塞回提示词让它自我修正：

```python
from pydantic import BaseModel, Field, ValidationError

class Product(BaseModel):
    name: str = Field(min_length=2)
    price: float = Field(gt=0, description="价格必须大于 0")


structured_llm = model.with_structured_output(Product)

text = "产品 A，价格是 -100 元"   # 故意给负价格，触发验证失败
prompt = f"提取产品信息：{text}"

for attempt in range(1, 4):
    try:
        result = structured_llm.invoke(prompt)
        print(f"第 {attempt} 次成功:", result)
        break
    except ValidationError as e:
        error_msg = e.errors()[0]["msg"]
        print(f"第 {attempt} 次失败: {error_msg}")
        prompt = f"{prompt}\n注意: {error_msg}。请修正后重新提取。"
```

流程：输出 `-100` → 验证失败 → 提示"价格必须 > 0" → 模型修正 → 通过。

---

## 单元格 7：组合策略——正确的调用顺序（在线）

**顺序必须是：`with_structured_output()` → `with_retry()` → `with_fallbacks()`**

原因：`with_retry()` 返回的 RunnableRetry 对象没有 `with_structured_output()` 方法，
先加 retry 后加 structured 会直接 AttributeError。

```python
# 1. 主模型：先创建结构化输出
primary_structured = model.with_structured_output(Product)

# 2. 备用模型：同样先创建结构化输出
fallback_structured = fallback.with_structured_output(Product)

# 3. 再加重试
primary_with_retry = primary_structured.with_retry(
    retry_if_exception_type=(ConnectionError, TimeoutError),
    stop_after_attempt=2,
)

# 4. 最后加降级
robust_extraction = primary_with_retry.with_fallbacks([fallback_structured])

result = robust_extraction.invoke("提取产品信息：产品 B，售价 999 元")
print(result)
```

防护层级：

```
Layer 1: Pydantic 验证      确保输出质量
Layer 2: with_retry()       处理临时网络错误
Layer 3: with_fallbacks()   处理模型故障
```

记忆规则：`structured_output → retry → fallbacks`（从内到外包装）。

---

## FAQ

### Q1: 重试次数设多少？

常规 3 次；高可用场景 5 次；快速失败 1 次。次数越多延迟越高。

### Q2: 如何避免无限重试循环？

永远用带上限的 for 循环，最后一次仍失败就抛异常或返回 None，不要 `while True` 裸重试。

### Q3: ValidationError 和网络异常怎么分开处理？

分别捕获：`ValidationError` 走"修正提示再提取"的重试循环；
网络类异常交给 `with_retry()` / `with_fallbacks()` 自动处理。

## 核心要点

1. `with_retry()` —— 临时性网络错误
2. `with_fallbacks()` —— 模型降级
3. Pydantic Field 约束 + `@field_validator` —— 数据质量防线
4. 验证失败时把错误信息回填提示词，让 LLM 自我修正
5. 组合顺序铁律：structured_output → retry → fallbacks

## 下一步

**13_rag_basics** —— RAG 基础：文档加载、分割、嵌入、向量检索
