# 项目三：智能研究助手（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量，跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。

## 项目目标

构建多阶段研究工作流：主题分析 → 信息收集 → 知识综合 → 报告生成。

## 0. 准备工作

```bash
pip install -U langchain langchain-groq langgraph pydantic python-dotenv
```

---

## 单元格 1：初始化模型

```python
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.3,
    max_tokens=1000,
)

print("模型就绪")
```

---

## 单元格 2：数据模型

```python
from pydantic import BaseModel, Field
from typing import Optional

class SearchResult(BaseModel):
    title: str
    source: str
    snippet: str
    relevance_score: float = Field(ge=0.0, le=1.0)

class ResearchOutline(BaseModel):
    title: str
    abstract: str
    sections: list[str]
    key_questions: list[str]

class Citation(BaseModel):
    id: str
    title: str
    source: str
    year: int

class ResearchReport(BaseModel):
    title: str
    executive_summary: str
    findings: list[str]
    analysis: str
    conclusions: list[str]
    recommendations: list[str]
    citations: list[Citation]
```

---

## 单元格 3：模拟搜索

```python
def mock_search(query: str) -> list[dict]:
    """模拟搜索结果"""
    mock_data = {
        "人工智能": [
            {"title": "AI 发展历程", "source": "tech_news", "snippet": "人工智能从1956年达特茅斯会议至今，经历了多次浪潮。"},
            {"title": "AI 应用领域", "source": "wiki", "snippet": "AI 应用于医疗、金融、教育、自动驾驶等多个领域。"},
        ],
        "机器学习": [
            {"title": "ML 基础概念", "source": "course", "snippet": "机器学习是AI子领域，通过数据训练模型进行预测。"},
        ],
    }
    for k, v in mock_data.items():
        if k in query:
            return v
    return [{"title": f"关于{query}的研究", "source": "general", "snippet": f"{query}是一个重要的研究方向。"}]
```

---

## 单元格 4：研究规划

```python
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

class ResearchState(TypedDict):
    messages: Annotated[list, add_messages]
    research_topic: str
    research_questions: list[str]
    search_results: list[dict]
    outline: dict
    findings: list[str]
    report: str

def plan_research(state: ResearchState) -> dict:
    messages = [
        SystemMessage(content="""你是研究规划专家。分析研究主题，生成：
1. 研究标题
2. 摘要（50字）
3. 研究问题（3-5个）
返回 JSON：{"title": "...", "abstract": "...", "questions": ["q1", "q2"]}"""),
        HumanMessage(content=f"研究主题：{state['research_topic']}")
    ]
    response = model.invoke(messages)
    try:
        content = response.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        outline = json.loads(content.strip())
    except:
        outline = {"title": state["research_topic"], "abstract": "研究概述", "questions": ["主要问题是什么？"]}
    return {
        "outline": outline,
        "research_questions": outline.get("questions", []),
        "messages": [AIMessage(content=f"[规划] 研究问题：{outline.get('questions', [])}")]
    }

print("规划节点就绪")
```

---

## 单元格 5：信息收集

```python
def collect_information(state: ResearchState) -> dict:
    all_results = []
    for q in state["research_questions"]:
        results = mock_search(q)
        all_results.extend(results)
    return {
        "search_results": all_results,
        "messages": [AIMessage(content=f"[收集] 找到 {len(all_results)} 条相关信息")]
    }

print("收集节点就绪")
```

---

## 单元格 6：知识综合

```python
def synthesize_findings(state: ResearchState) -> dict:
    results_text = "\n".join(f"- {r['title']}: {r['snippet']}" for r in state["search_results"])
    messages = [
        SystemMessage(content="根据以下搜索结果，提取3-5个关键发现。每个发现用一句话概括。"),
        HumanMessage(content=f"研究问题：{state['research_questions']}\n\n搜索结果：\n{results_text}")
    ]
    response = model.invoke(messages)
    findings = [f.strip() for f in response.content.split("\n") if f.strip() and not f.strip().startswith("#")]
    return {
        "findings": findings[:5],
        "messages": [AIMessage(content=f"[综合] 提取了 {len(findings)} 个关键发现")]
    }

print("综合节点就绪")
```

---

## 单元格 7：报告生成

```python
def generate_report(state: ResearchState) -> dict:
    findings_text = "\n".join(f"{i+1}. {f}" for i, f in enumerate(state["findings"]))
    messages = [
        SystemMessage(content="""你是研究报告撰写专家。根据以下信息生成研究报告。

格式要求：
- 执行摘要（100字）
- 主要发现
- 分析
- 结论和建议

用中文撰写。"""),
        HumanMessage(content=f"主题：{state['outline'].get('title', state['research_topic'])}\n关键发现：\n{findings_text}")
    ]
    response = model.invoke(messages)
    return {
        "report": response.content,
        "messages": [AIMessage(content="[报告] 研究报告生成完成")]
    }

print("报告节点就绪")
```

---

## 单元格 8：构建研究工作流

```python
graph = StateGraph(ResearchState)

graph.add_node("plan", plan_research)
graph.add_node("collect", collect_information)
graph.add_node("synthesize", synthesize_findings)
graph.add_node("report", generate_report)

graph.add_edge(START, "plan")
graph.add_edge("plan", "collect")
graph.add_edge("collect", "synthesize")
graph.add_edge("synthesize", "report")
graph.add_edge("report", END)

research_app = graph.compile()
print("研究工作流就绪")
```

---

## 单元格 9：运行研究

```python
result = research_app.invoke({
    "messages": [],
    "research_topic": "人工智能在医疗领域的应用",
    "research_questions": [],
    "search_results": [],
    "outline": {},
    "findings": [],
    "report": ""
})

print("=" * 60)
print("研究报告")
print("=" * 60)
print(f"主题: {result['outline'].get('title', 'N/A')}")
print(f"摘要: {result['outline'].get('abstract', 'N/A')}")
print(f"\n研究问题:")
for q in result["research_questions"]:
    print(f"  - {q}")
print(f"\n关键发现:")
for f in result["findings"]:
    print(f"  - {f}")
print(f"\n报告:\n{result['report']}")
```

---

## 核心要点

1. **多阶段工作流**：规划 → 收集 → 综合 → 报告，线性图
2. **Pydantic 数据模型**：结构化输出（大纲、报告）
3. **模拟搜索**：可替换为真实搜索 API
4. **状态传递**：每个阶段的输出喂给下一个阶段

## 进阶优化方向

- 集成真实搜索 API（Tavily、SerpAPI）
- 添加 PDF/文献解析
- 迭代式报告优化循环
- 多语言研究支持

## 完成

恭喜完成 LangGraph 教程全部内容！🎉

你已经掌握了：
- LangGraph 状态图基础
- 多 Agent 协作模式
- 条件路由和决策树
- 多模态处理
- 错误处理和降级
- 完整项目实战
