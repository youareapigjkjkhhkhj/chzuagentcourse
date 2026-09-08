# 11 - Structured Output：结构化输出（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `model`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` / `test.py` 是等价的脚本版本，本手册不修改它们。
> - **本模块需要在线模型**：`with_structured_output()` 依赖模型的 function calling 能力。Groq 的 Llama-3.3-70B 支持；离线 pipeline 方式加载的本地小模型不支持。

## 学习目标

**Structured Output = 将 LLM 的自然语言输出转为结构化 Python 对象**

1. `with_structured_output()` + Pydantic 模型
2. Field 描述、类型注解、可选字段、枚举
3. 列表提取与嵌套模型
4. 实战：信息提取

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
    temperature=0,      # 信息提取用低温度，更稳定
    max_tokens=500,
)

print("就绪")
```

---

## 单元格 2：第一个结构化提取

对比：传统方式要"要求 JSON → 手动解析 → 手动验证 → 手动建对象"四步；
`with_structured_output()` 一步到位，自动解析、验证、创建对象：

```python
from pydantic import BaseModel, Field

class Person(BaseModel):
    """人物信息"""
    name: str = Field(description="姓名")
    age: int = Field(description="年龄")
    occupation: str = Field(description="职业")


structured_llm = model.with_structured_output(Person)

result = structured_llm.invoke("张三是一名 30 岁的软件工程师")

print(type(result))            # Person —— 不是字符串，是 Pydantic 对象！
print(result.name)             # 直接用属性访问
print(result.age)
print(result.occupation)
```

幕后流程：Pydantic 模型 → JSON Schema → 强制 LLM 按 schema 返回 → 自动验证并实例化。

---

## 单元格 3：丰富的类型注解

```python
from typing import Optional, List

class Product(BaseModel):
    name: str                              # 必填字符串
    price: float                           # 必填浮点数
    description: Optional[str] = None      # 可选，可能提取不到
    tags: List[str] = Field(description="产品标签，如 '电子产品', '手机'")


product_llm = model.with_structured_output(Product)

r = product_llm.invoke(
    "iPhone 15 Pro，售价 8999 元，主打钛金属设计和 A17 芯片，标签：手机、苹果、旗舰"
)
print(r.name, r.price)
print(r.tags)          # 列表
print(r.description)   # 可能是 None 或文本
```

要点：
- `description` 会传给 LLM，写得越清楚提取越准
- 不确定存在的字段用 `Optional[T] = None`，避免强制必填导致整体失败

---

## 单元格 4：枚举约束——限制可选值

```python
from enum import Enum

class Priority(str, Enum):
    LOW = "低"
    MEDIUM = "中"
    HIGH = "高"

class Task(BaseModel):
    title: str = Field(description="任务标题")
    priority: Priority = Field(description="优先级")


task_llm = model.with_structured_output(Task)

t = task_llm.invoke("线上服务器宕机了，需要立刻修复！")
print(t.title, "->", t.priority)   # priority 只可能是 低/中/高
```

需要限定取值范围的字段一律用枚举，比裸字符串可靠得多。

---

## 单元格 5：列表提取

一次提取多个对象：

```python
class Person(BaseModel):
    name: str
    age: int

class PeopleList(BaseModel):
    people: List[Person] = Field(description="提取到的所有人")


people_llm = model.with_structured_output(PeopleList)

r = people_llm.invoke("张三 30 岁，是工程师；李四 25 岁，是设计师；王五 28 岁，是产品经理")
for p in r.people:
    print(f"{p.name} {p.age}")
```

技巧：想提取"多个 X"，就包一层 `class XList(BaseModel): items: List[X]`。

---

## 单元格 6：嵌套模型

```python
class Address(BaseModel):
    city: str = Field(description="城市")
    district: str = Field(description="区/县")

class Company(BaseModel):
    name: str = Field(description="公司名")
    address: Address = Field(description="公司地址")


company_llm = model.with_structured_output(Company)

c = company_llm.invoke("阿里巴巴总部在杭州余杭区")
print(c.name)
print(c.address.city, c.address.district)   # 嵌套属性直接访问
```

嵌套建议不超过 3 层，层级越深越容易出错。

---

## 单元格 7：实战——客户信息提取

```python
class CustomerInfo(BaseModel):
    name: str = Field(description="客户姓名")
    phone: str = Field(description="电话号码")
    email: Optional[str] = Field(None, description="邮箱，可能没有")
    issue: str = Field(description="问题描述")


crm_llm = model.with_structured_output(CustomerInfo)

conversation = "客户: 我是李明，电话 13812345678，订单三天了还没发货"

info = crm_llm.invoke(f"提取客户信息：{conversation}")

print("姓名:", info.name)
print("电话:", info.phone)
print("邮箱:", info.email)
print("问题:", info.issue)
# 可直接写入 CRM / 工单系统
```

---

## 单元格 8：实战——评论分析

```python
class Review(BaseModel):
    product: str = Field(description="产品名")
    rating: int = Field(description="评分 1-5")
    pros: List[str] = Field(description="优点列表")
    cons: List[str] = Field(description="缺点列表")


review_llm = model.with_structured_output(Review)

r = review_llm.invoke(
    "iPhone 15 很棒！摄像头强大，手感好。但是价格贵，没有充电器。总体 4 分。"
)

print("产品:", r.product)
print("评分:", r.rating)
print("优点:", r.pros)
print("缺点:", r.cons)
```

---

## FAQ

### Q1: LLM 没填充某些字段怎么办？

该字段改成 `Optional[T] = None` 或给默认值；必填字段过多容易导致整体提取失败。

### Q2: 所有模型都支持吗？

依赖 function calling 的现代模型支持（OpenAI / Anthropic / Groq llama-3 等）；
离线 pipeline 小模型不支持。个别不支持时 LangChain 会回退到提示词 + JSON 解析，但稳定性差。

### Q3: 复杂嵌套总出错？

控制层级 ≤ 3、每个字段写清楚 description、必要时拆成多次调用。

### Q4: 提取结果还是不可靠怎么办？

加验证和重试机制——正是下一模块的主题。

## 最佳实践速查

- 字段必须写 `Field(description=...)`，格式要求写进描述（如 "YYYY-MM-DD"）
- 取值固定的字段用枚举
- 数量不确定的信息用 `Optional`
- 嵌套保持简单

## 核心要点

1. `model.with_structured_output(Schema)` 返回 Pydantic 对象
2. `Field(description=...)` 是给 LLM 看的字段说明
3. `Optional[T]` / 默认值 / 枚举提高鲁棒性
4. 多对象提取用包装类 + `List[T]`
5. 嵌套 ≤ 3 层

## 下一步

**12_validation_retry** —— 验证提取结果，失败自动重试
