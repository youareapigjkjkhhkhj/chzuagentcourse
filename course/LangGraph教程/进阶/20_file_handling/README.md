# 20 - 文件处理（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量，跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。

## 学习目标

1. 文档加载器（TextLoader、CSV、JSON）
2. 文本分割（RecursiveCharacterTextSplitter）
3. Document 对象结构
4. LLM 辅助文档分析

## 0. 准备工作

```bash
pip install -U langchain langchain-groq langchain-community langchain-text-splitters python-dotenv
```

---

## 单元格 1：初始化模型

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
    max_tokens=500,
)

print("模型就绪")
```

---

## 单元格 2：创建示例文件

```python
import tempfile, os, csv, json

temp_dir = tempfile.mkdtemp()

# TXT 文件
txt_path = os.path.join(temp_dir, "python_guide.txt")
with open(txt_path, "w", encoding="utf-8") as f:
    f.write("""# Python 编程入门指南

## 第一章：Python 简介
Python 是一种广泛使用的高级编程语言，由 Guido van Rossum 于 1989 年创建。
Python 的设计哲学强调代码的可读性和简洁性。

### 1.1 Python 的特点
- **简单易学**：语法简洁清晰
- **跨平台**：可在 Windows、Mac、Linux 上运行
- **丰富的库**：拥有大量第三方库

## 第二章：基础语法
Python 支持多种数据类型：整数(int)、浮点数(float)、字符串(str)、列表(list)、字典(dict)

## 总结
Python 是一门优秀的编程语言，适合初学者入门。""")

# CSV 文件
csv_path = os.path.join(temp_dir, "employees.csv")
with open(csv_path, "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["姓名", "年龄", "城市", "职业"])
    writer.writerows([
        ["张三", 28, "北京", "工程师"],
        ["李四", 32, "上海", "产品经理"],
        ["王五", 25, "广州", "设计师"],
    ])

# JSON 文件
json_path = os.path.join(temp_dir, "company.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump({
        "company": "科技有限公司",
        "founded": 2020,
        "products": [
            {"name": "产品A", "price": 99.9, "category": "软件"},
            {"name": "产品B", "price": 199.9, "category": "服务"},
        ]
    }, f, ensure_ascii=False, indent=2)

print(f"临时目录: {temp_dir}")
```

---

## 单元格 3：文本加载——Document 对象

```python
from langchain_core.documents import Document

with open(txt_path, "r", encoding="utf-8") as f:
    content = f.read()

doc = Document(
    page_content=content,
    metadata={"source": txt_path, "type": "text"}
)

print(f"字符数: {len(doc.page_content)}")
print(f"元数据: {doc.metadata}")
print(f"\n前200字:\n{doc.page_content[:200]}")
```

---

## 单元格 4：文本分割——分块

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=300,
    chunk_overlap=30,
    separators=["\n## ", "\n### ", "\n\n", "\n", "。", " "],
)

chunks = splitter.split_documents([doc])

print(f"原文: {len(content)} 字符 → 分割为 {len(chunks)} 块")
for i, c in enumerate(chunks):
    print(f"  块{i+1}: {len(c.page_content)} 字符 | {c.page_content[:40]}...")
```

---

## 单元格 5：CSV 处理

```python
import csv

with open(csv_path, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

docs = [
    Document(page_content=str(row), metadata={"source": csv_path, "row": i+1})
    for i, row in enumerate(rows)
]

print(f"加载 {len(docs)} 条记录:")
for d in docs:
    print(f"  第{d.metadata['row']}行: {d.page_content}")

# LLM 分析
from langchain_core.messages import HumanMessage, SystemMessage
csv_text = "\n".join(d.page_content for d in docs)
response = model.invoke([
    SystemMessage(content="你是数据分析专家。用中文简洁分析以下数据。"),
    HumanMessage(content=f"员工数据：\n{csv_text}")
])
print(f"\n分析:\n{response.content}")
```

---

## 单元格 6：JSON 处理

```python
with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

formatted = json.dumps(data, ensure_ascii=False, indent=2)
doc = Document(
    page_content=formatted,
    metadata={"source": json_path, "type": "json", "keys": list(data.keys())}
)

print(f"顶级键: {doc.metadata['keys']}")
print(f"\n内容预览:\n{formatted[:300]}")

response = model.invoke([
    SystemMessage(content="解释这个 JSON 的结构和用途。用中文回答。"),
    HumanMessage(content=formatted)
])
print(f"\n分析:\n{response.content}")
```

---

## 单元格 7：文档问答

```python
with open(txt_path, "r", encoding="utf-8") as f:
    txt_content = f.read()

questions = ["Python 是什么时候创建的？", "Python 有哪些主要数据类型？"]

for q in questions:
    response = model.invoke([
        SystemMessage(content=f"根据以下文档回答问题。如果没有相关信息请说明。\n\n{txt_content}"),
        HumanMessage(content=q)
    ])
    print(f"Q: {q}")
    print(f"A: {response.content}\n")
```

---

## 单元格 8：清理临时文件

```python
import shutil
shutil.rmtree(temp_dir)
print("临时文件已清理")
```

---

## 核心要点

1. **Document = page_content + metadata**，是 LangChain 的标准文档单元
2. **RecursiveCharacterTextSplitter** 按优先级分割，保持语义完整
3. chunk_size / chunk_overlap 控制块大小和重叠
4. CSV / JSON 先转为 Document 再交给 LLM 分析

## FAQ

### Q1: chunk_size 设多少合适？

通用 500；长文档 1000；短问答对 200。重叠通常为 chunk_size 的 10%。

### Q2: 大目录怎么批量加载？

用 `DirectoryLoader`：`DirectoryLoader("data/", glob="**/*.txt", loader_cls=TextLoader)`

## 下一步

**21_mixed_modality** —— 混合模态：文本+图像+结构化数据的综合处理
