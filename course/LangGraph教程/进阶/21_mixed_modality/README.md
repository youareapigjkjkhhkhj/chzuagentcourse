# 21 - 混合模态（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量，跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。

## 学习目标

在同一个工作流中处理**文本 + 图像 + 结构化数据**。

应用场景：报告生成、内容审核、智能文档处理、数据可视化解读。

## 0. 准备工作

```bash
pip install -U langchain langchain-openai langgraph python-dotenv
```

需要 `OPENAI_API_KEY`（图像处理必须用视觉模型）。

> 如果没有 OpenAI Key，可以先阅读代码理解模式。

---

## 单元格 1：初始化视觉模型

```python
import os
import base64
from pathlib import Path
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

model = init_chat_model(
    "openai:gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0,
    max_tokens=500,
)

IMAGES_DIR = Path("images")
IMAGES_DIR.mkdir(exist_ok=True)

print("模型就绪")
```

---

## 单元格 2：图像编码工具

```python
from langchain_core.messages import HumanMessage

def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")

def get_mime(image_path: str) -> str:
    ext = Path(image_path).suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(ext, "image/jpeg")

def image_block(image_path: str) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:{get_mime(image_path)};base64,{encode_image(image_path)}"}}
```

---

## 单元格 3：文本+图像混合输入

> 运行前请在 `images/` 目录放入一张图表图片 `chart.png`。没有图片可跳过。

```python
chart_path = "images/chart.png"

if Path(chart_path).exists():
    content = [
        {"type": "text", "text": """以下是销售数据：
- 1月: 150万
- 2月: 180万
- 3月: 220万

请结合图表分析趋势、一致性、建议。"""},
        image_block(chart_path)
    ]
    response = model.invoke([HumanMessage(content=content)])
    print(response.content)
else:
    print("无 chart.png，跳过。请在 images/ 放入图表图片后重试。")
```

---

## 单元格 4：LangGraph 混合模态工作流

```python
from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, START, END

class MultimodalState(TypedDict):
    text_input: str
    image_paths: List[str]
    analysis_result: Optional[str]
    summary: Optional[str]

def analyze_content(state: MultimodalState) -> dict:
    content = [{"type": "text", "text": state["text_input"]}]
    for p in state["image_paths"]:
        if Path(p).exists():
            content.append(image_block(p))
    response = model.invoke([HumanMessage(content=content)])
    return {"analysis_result": response.content}

def summarize(state: MultimodalState) -> dict:
    response = model.invoke([
        HumanMessage(content=f"用3句话总结：\n{state['analysis_result']}")
    ])
    return {"summary": response.content}

graph = StateGraph(MultimodalState)
graph.add_node("analyze", analyze_content)
graph.add_node("summarize", summarize)
graph.add_edge(START, "analyze")
graph.add_edge("analyze", "summarize")
graph.add_edge("summarize", END)

workflow = graph.compile()

# 使用纯文本测试（无图片也能跑）
result = workflow.invoke({
    "text_input": "请分析以下数据的趋势并给出建议：Q1销售150万，Q2销售180万，Q3销售220万。",
    "image_paths": [],
    "analysis_result": None,
    "summary": None
})

print("分析：", result["analysis_result"])
print("总结：", result["summary"])
```

---

## 核心要点

1. `HumanMessage(content=[...])` 可混合文本块和图像块
2. 图像块格式：`{"type": "image_url", "image_url": {"url": "data:image/xxx;base64,..."}}`
3. LangGraph 工作流中嵌入多模态处理：analyze → summarize
4. 纯文本也能跑多模态工作流（图像路径列表为空即可）

## FAQ

### Q1: 能同时处理多张图片吗？

可以，`image_paths` 列表放多个路径，每个都会转为 image_url 块加入消息。

### Q2: 什么时候用 LangGraph 而不是直接调用？

单步处理直接调用即可；多步骤（分析→总结→格式化）或需要条件路由时用 LangGraph。

## 下一步

**22_langsmith_integration** —— LangSmith 集成：追踪、监控、性能分析
