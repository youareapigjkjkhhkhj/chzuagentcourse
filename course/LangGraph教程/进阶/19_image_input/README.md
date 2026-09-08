# 19 - 图像输入（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `model`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。

## 学习目标

1. 用视觉模型（GPT-4o-mini）处理图像输入
2. 本地图像 Base64 编码
3. 图像描述、问答、OCR、图表分析

## 0. 准备工作

```bash
pip install -U langchain langchain-openai python-dotenv
```

需要 `OPENAI_API_KEY`（图像处理必须用支持视觉的模型）。

> 如果你没有 OpenAI Key，本模块的图像处理单元格无法运行。
> 可以先阅读代码理解模式，之后再实操。

---

## 单元格 1：初始化视觉模型

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

model = init_chat_model(
    "openai:gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0,
    max_tokens=500,
)

print("视觉模型就绪")
```

---

## 单元格 2：图像编码工具函数

```python
import base64
from pathlib import Path

IMAGES_DIR = Path("images")
IMAGES_DIR.mkdir(exist_ok=True)

def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")

def get_mime(image_path: str) -> str:
    ext = Path(image_path).suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(ext, "image/jpeg")

def create_image_message(text: str, image_path: str):
    """创建包含本地图像的 HumanMessage"""
    from langchain_core.messages import HumanMessage
    return HumanMessage(content=[
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": f"data:{get_mime(image_path)};base64,{encode_image(image_path)}"}}
    ])

print("工具函数就绪")
```

---

## 单元格 3：图像描述

> 运行前请将一张测试图片放入 `images/` 目录（如 `images/sample.jpg`）。
> 没有图片可以先跳过此单元格，阅读代码理解模式。

```python
from langchain_core.messages import HumanMessage

image_path = "images/sample.jpg"

if Path(image_path).exists():
    msg = create_image_message("请详细描述这张图片的内容。", image_path)
    response = model.invoke([msg])
    print("描述：")
    print(response.content)
else:
    print(f"图片不存在: {image_path}")
    print("请将测试图片放入 images/ 目录，然后重新运行此单元格。")
```

---

## 单元格 4：图像问答（多轮）

```python
if Path(image_path).exists():
    messages = [create_image_message("我会问你关于这张图片的问题。", image_path)]

    for q in ["图片中有什么主要物体？", "整体色调是什么？"]:
        messages.append(HumanMessage(content=q))
        response = model.invoke(messages)
        messages.append(response)
        print(f"Q: {q}")
        print(f"A: {response.content}\n")
else:
    print("跳过（无图片）")
```

---

## 单元格 5：OCR 文字识别

```python
text_image = "images/text_image.jpg"

if Path(text_image).exists():
    msg = create_image_message(
        "请执行以下任务：1. 描述图片内容 2. 提取所有可见文字 3. 说明图片类型",
        text_image
    )
    response = model.invoke([msg])
    print("OCR 结果：")
    print(response.content)
else:
    print(f"图片不存在: {text_image}")
    print("请准备一张包含文字的图片，放入 images/text_image.jpg")
```

---

## 单元格 6：图表分析

```python
chart_image = "images/chart.png"

if Path(chart_image).exists():
    msg = create_image_message(
        "请分析这个图表：1. 图表类型 2. 展示的数据 3. 关键结论 4. 提取数值",
        chart_image
    )
    response = model.invoke([msg])
    print("分析结果：")
    print(response.content)
else:
    print(f"图片不存在: {chart_image}")
    print("请准备一张图表图片，放入 images/chart.png")
```

---

## 核心要点

1. 本地图像 → Base64 编码 → `data:image/xxx;base64,...` 格式
2. `HumanMessage` 的 `content` 是列表，可混合文本和图像
3. 图像消耗大量 token，注意成本
4. 必须用支持视觉的模型（GPT-4o / GPT-4o-mini / Claude 3.5）

## FAQ

### Q1: 能用 Groq 处理图像吗？

Groq 的 Llama 模型不支持图像输入。图像处理必须用 OpenAI / Anthropic / Gemini 等视觉模型。

### Q2: Base64 编码会很大吗？

是的，约增加 33% 体积。大图建议先压缩。

## 下一步

**20_file_handling** —— 文件处理：文档加载、分块、多格式支持
