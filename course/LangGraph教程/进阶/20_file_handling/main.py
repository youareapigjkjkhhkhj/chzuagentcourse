"""
模块 20：文件处理
学习如何加载和处理各种文件类型
"""

import os
import tempfile
from typing import List
from dotenv import load_dotenv

from langchain.chat_models import init_chat_model
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 加载环境变量
load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
    raise ValueError(
        "\n请先在 .env 文件中设置有效的 GROQ_API_KEY\n"
        "访问 https://console.groq.com/keys 获取免费密钥"
    )

# 初始化模型
model = init_chat_model("groq:llama-3.3-70b-versatile", api_key=GROQ_API_KEY)

    # 初始化模型

# ============================================================
# 辅助函数：创建示例文件
# ============================================================

def create_sample_files():
    """创建用于演示的示例文件"""
    temp_dir = tempfile.mkdtemp()
    
    # 创建示例文本文件
    sample_text = """# Python 编程入门指南

## 第一章：Python 简介

Python 是一种广泛使用的高级编程语言，由 Guido van Rossum 于 1989 年创建。
Python 的设计哲学强调代码的可读性和简洁性。

### 1.1 Python 的特点

- **简单易学**：Python 语法简洁清晰
- **跨平台**：可在 Windows、Mac、Linux 上运行
- **丰富的库**：拥有大量第三方库支持

### 1.2 安装 Python

可以从 python.org 下载最新版本。

## 第二章：基础语法

### 2.1 变量和数据类型

Python 支持多种数据类型：
- 整数 (int)
- 浮点数 (float)
- 字符串 (str)
- 列表 (list)
- 字典 (dict)

### 2.2 控制流程

Python 使用缩进来表示代码块：

```python
if condition:
    # 执行代码
    pass
elif other_condition:
    # 其他代码
    pass
else:
    # 默认代码
    pass
```

## 第三章：函数

函数是组织代码的重要方式：

```python
def greet(name):
    return f"Hello, {name}!"
```

## 总结

Python 是一门优秀的编程语言，适合初学者入门，也能满足专业开发需求。
"""
    
    txt_path = os.path.join(temp_dir, "python_guide.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(sample_text)
    
    # 创建 CSV 示例
    csv_content = """姓名,年龄,城市,职业
张三,28,北京,工程师
李四,32,上海,产品经理
王五,25,广州,设计师
赵六,35,深圳,数据分析师
"""
    csv_path = os.path.join(temp_dir, "employees.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(csv_content)
    
    # 创建 JSON 示例
    json_content = """{
    "company": "科技有限公司",
    "founded": 2020,
    "products": [
        {"name": "产品A", "price": 99.9, "category": "软件"},
        {"name": "产品B", "price": 199.9, "category": "服务"},
        {"name": "产品C", "price": 299.9, "category": "硬件"}
    ],
    "locations": ["北京", "上海", "深圳"]
}"""
    json_path = os.path.join(temp_dir, "company.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(json_content)
    
    return temp_dir, txt_path, csv_path, json_path

# ============================================================
# 示例 1：基本文本文件加载
# ============================================================

def basic_text_loading(txt_path: str):
    """
    加载和处理文本文件
    """
    print("\n" + "=" * 60)
    print("示例 1：基本文本文件加载")
    print("=" * 60)

    # 读取文件
    with open(txt_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 创建 Document 对象
    doc = Document(
        page_content=content,
        metadata={
            "source": txt_path,
            "type": "text",
            "encoding": "utf-8"
        }
    )
    
    print(f"📄 已加载文件: {os.path.basename(txt_path)}")
    print(f"   字符数: {len(doc.page_content)}")
    print(f"   元数据: {doc.metadata}")
    
    # 使用 LLM 分析文档
    messages = [
        SystemMessage(content="你是一个文档分析专家。请分析以下文档的结构和主要内容。用中文简洁回答。"),
        HumanMessage(content=f"文档内容：\n\n{doc.page_content[:2000]}")  # 限制长度
    ]
    
    response = model.invoke(messages)
    print("\n📊 文档分析：")
    print(response.content)
    
    return doc

# ============================================================
# 示例 2：文档分块
# ============================================================

def document_chunking(txt_path: str):
    """
    将长文档分割成小块
    """
    print("\n" + "=" * 60)
    print("示例 2：文档分块")
    print("=" * 60)

    # 读取文件
    with open(txt_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    doc = Document(page_content=content, metadata={"source": txt_path})
    
    # 创建文本分割器
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,        # 每块约 500 字符
        chunk_overlap=50,      # 重叠 50 字符以保持上下文
        separators=["\n## ", "\n### ", "\n\n", "\n", "。", " "],
        length_function=len
    )
    
    # 分割文档
    chunks = splitter.split_documents([doc])
    
    print(f"📑 原文档长度: {len(content)} 字符")
    print(f"📑 分割成 {len(chunks)} 个块")
    print("\n各块信息：")
    
    for i, chunk in enumerate(chunks[:5]):  # 只显示前5个
        print(f"  块 {i+1}: {len(chunk.page_content)} 字符")
        print(f"    开头: {chunk.page_content[:50]}...")
    
    if len(chunks) > 5:
        print(f"  ... 还有 {len(chunks) - 5} 个块")
    
    return chunks

# ============================================================
# 示例 3：CSV 文件处理
# ============================================================

def csv_processing(csv_path: str):
    """
    处理 CSV 文件
    """
    print("\n" + "=" * 60)
    print("示例 3：CSV 文件处理")
    print("=" * 60)

    import csv
    
    # 读取 CSV
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    # 将每行转为 Document
    documents = []
    for i, row in enumerate(rows):
        doc = Document(
            page_content=str(row),
            metadata={"source": csv_path, "row": i + 1}
        )
        documents.append(doc)
    
    print(f"📊 已加载 {len(documents)} 条记录")
    print("\n前几条记录：")
    for doc in documents[:3]:
        print(f"  第 {doc.metadata['row']} 行: {doc.page_content}")
    
    # 使用 LLM 分析 CSV 数据
    csv_content = "\n".join([doc.page_content for doc in documents])
    
    messages = [
        SystemMessage(content="你是一个数据分析专家。请分析以下数据并给出见解。用中文回答。"),
        HumanMessage(content=f"数据内容：\n{csv_content}")
    ]
    
    response = model.invoke(messages)
    print("\n📈 数据分析：")
    print(response.content)
    
    return documents

# ============================================================
# 示例 4：JSON 文件处理
# ============================================================

def json_processing(json_path: str):
    """
    处理 JSON 文件
    """
    print("\n" + "=" * 60)
    print("示例 4：JSON 文件处理")
    print("=" * 60)

    import json
    
    # 读取 JSON
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # 将 JSON 转为格式化文本
    formatted_json = json.dumps(data, ensure_ascii=False, indent=2)
    
    doc = Document(
        page_content=formatted_json,
        metadata={
            "source": json_path,
            "type": "json",
            "keys": list(data.keys())
        }
    )
    
    print("📋 JSON 结构：")
    print(f"   顶级键: {doc.metadata['keys']}")
    print("\n内容预览：")
    print(formatted_json[:500])
    
    # 使用 LLM 理解 JSON 结构
    messages = [
        SystemMessage(content="你是一个数据结构专家。请解释这个 JSON 的结构和用途。用中文回答。"),
        HumanMessage(content=f"JSON 内容：\n{formatted_json}")
    ]
    
    response = model.invoke(messages)
    print("\n🔍 结构分析：")
    print(response.content)
    
    return doc

# ============================================================
# 示例 5：文档问答
# ============================================================

def document_qa(txt_path: str):
    """
    基于文档内容回答问题
    """
    print("\n" + "=" * 60)
    print("示例 5：文档问答")
    print("=" * 60)

    # 读取文件
    with open(txt_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    questions = [
        "Python 是什么时候创建的？",
        "Python 有哪些主要数据类型？",
        "如何在 Python 中定义函数？"
    ]
    
    print("📖 基于文档回答问题：\n")
    
    for question in questions:
        messages = [
            SystemMessage(content=f"""你是一个文档问答助手。根据以下文档内容回答问题。
如果文档中没有相关信息，请说明"文档中未提及此信息"。
用中文简洁回答。

文档内容：
{content}"""),
            HumanMessage(content=question)
        ]
        
        response = model.invoke(messages)
        
        print(f"❓ 问题: {question}")
        print(f"💬 回答: {response.content}\n")

# ============================================================
# 示例 6：多文件合并分析
# ============================================================

def multi_file_analysis(temp_dir: str, txt_path: str, csv_path: str, json_path: str):
    """
    合并多个文件进行综合分析
    """
    print("\n" + "=" * 60)
    print("示例 6：多文件合并分析")
    print("=" * 60)

    # 加载所有文件
    documents = []
    
    # 文本文件
    with open(txt_path, "r", encoding="utf-8") as f:
        documents.append(Document(
            page_content=f.read()[:1000],  # 限制长度
            metadata={"source": "python_guide.txt", "type": "tutorial"}
        ))
    
    # CSV 文件
    with open(csv_path, "r", encoding="utf-8") as f:
        documents.append(Document(
            page_content=f.read(),
            metadata={"source": "employees.csv", "type": "data"}
        ))
    
    # JSON 文件
    with open(json_path, "r", encoding="utf-8") as f:
        documents.append(Document(
            page_content=f.read(),
            metadata={"source": "company.json", "type": "config"}
        ))
    
    print(f"📁 已加载 {len(documents)} 个文件：")
    for doc in documents:
        print(f"   - {doc.metadata['source']} ({doc.metadata['type']})")
    
    # 合并内容
    combined_content = "\n\n---\n\n".join([
        f"【{doc.metadata['source']}】\n{doc.page_content}"
        for doc in documents
    ])
    
    # 综合分析
    messages = [
        SystemMessage(content="你是一个综合分析专家。请分析以下多个文件的内容，找出它们之间的联系，并给出综合见解。用中文回答。"),
        HumanMessage(content=combined_content)
    ]
    
    response = model.invoke(messages)
    
    print("\n🔗 综合分析：")
    print(response.content)
    
    return documents

# ============================================================
# 主程序
# ============================================================

if __name__ == "__main__":
    print("文件处理教程")
    print("=" * 60)
    
    # 创建示例文件
    temp_dir, txt_path, csv_path, json_path = create_sample_files()
    print(f"已创建示例文件于: {temp_dir}")
    
    try:
        # 运行示例
        basic_text_loading(txt_path)
        document_chunking(txt_path)
        csv_processing(csv_path)
        json_processing(json_path)
        document_qa(txt_path)
        multi_file_analysis(temp_dir, txt_path, csv_path, json_path)
        
    finally:
        # 清理临时文件
        import shutil
        shutil.rmtree(temp_dir)
        print("\n已清理临时文件")
    
    print("\n" + "=" * 60)
    print("✅ 所有示例运行完成！")
    print("=" * 60)
